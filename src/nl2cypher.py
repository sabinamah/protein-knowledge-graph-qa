#!/usr/bin/env python3
"""Natural-language -> Cypher translation with pluggable backends.

Backends (selected by config.LLM_BACKEND):
    template   rule-based intent matcher. No API key, no GPU, always works.
    anthropic  Claude translates the question to Cypher (needs ANTHROPIC_API_KEY).
    ollama     a local open model does the translation (needs Ollama running).

All backends return a single read-only Cypher query. The caller
(`ask.py`) executes it and shows the query + retrieved rows alongside the
answer, so every answer is traceable to explicit graph evidence.
"""
import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C

# --------------------------------------------------------------------------- #
# Schema description shared with the LLM backends.
# --------------------------------------------------------------------------- #
SCHEMA = """
Graph schema (Neo4j):

Nodes:
  (:Protein {string_id, gene_name, protein_name, abundance, abundance_rank, uniprot})
  (:Function {go_id, name})     // GO molecular-function terms
  (:Pathway {name})             // curated pathway names

Relationships:
  (:Protein)-[:INTERACTS_WITH {score}]->(:Protein)   // STRING, treat as undirected
  (:Protein)-[:HAS_FUNCTION]->(:Function)
  (:Protein)-[:PARTICIPATES_IN]->(:Pathway)

Notes:
- Proteins are the 200 most-abundant proteins of one organism.
- Match proteins by gene_name (e.g. 'gapA'), which is lower/mixed case.
- INTERACTS_WITH has no meaningful direction; match it undirected: -[:INTERACTS_WITH]-.
"""

CYPHER_INSTRUCTIONS = (
    "Translate the user's question into ONE read-only Cypher query for the schema "
    "above. Return ONLY the Cypher, no prose, no markdown fences. Never write, "
    "merge, delete or set anything. Always LIMIT results to at most 25 rows."
)


# --------------------------------------------------------------------------- #
# Backend: template (rule-based)
# --------------------------------------------------------------------------- #
def _find_genes(question: str, vocab: set[str]) -> list[str]:
    """Pull gene names the graph actually knows out of the question."""
    found = []
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9]+", question):
        # gene names are case-sensitive-ish; match case-insensitively but
        # return the canonical spelling from the vocabulary.
        for g in vocab:
            if tok.lower() == g.lower() and g not in found:
                found.append(g)
    return found


def template_to_cypher(question: str, vocab: set[str]) -> tuple[str, str]:
    """Return (cypher, matched_intent). Raises ValueError if no rule matches."""
    q = question.lower()
    genes = _find_genes(question, vocab)
    g0 = f"'{genes[0]}'" if genes else None
    g1 = f"'{genes[1]}'" if len(genes) > 1 else None

    # shortest path / how connected -- needs two genes
    if g0 and g1 and any(k in q for k in ("path", "connect", "linked", "between")):
        return (
            f"MATCH path = shortestPath((a:Protein {{gene_name: {g0}}})"
            f"-[:INTERACTS_WITH*..6]-(b:Protein {{gene_name: {g1}}})) "
            "RETURN [n IN nodes(path) | n.gene_name] AS path, length(path) AS hops",
            "shortest_path",
        )

    # interaction partners
    if g0 and any(k in q for k in ("interact", "partner", "bind", "neighbou")):
        return (
            f"MATCH (p:Protein {{gene_name: {g0}}})-[e:INTERACTS_WITH]-(o:Protein) "
            "RETURN o.gene_name AS partner, o.protein_name AS name, e.score AS score "
            "ORDER BY score DESC LIMIT 25",
            "interaction_partners",
        )

    # proteins sharing a function with X (check before generic "functions of X")
    if g0 and "shar" in q and "function" in q:
        return (
            f"MATCH (x:Protein {{gene_name: {g0}}})-[:HAS_FUNCTION]->(f:Function)"
            "<-[:HAS_FUNCTION]-(o:Protein) WHERE o <> x "
            "RETURN DISTINCT o.gene_name AS protein, f.name AS shared_function "
            "ORDER BY protein LIMIT 25",
            "shared_function",
        )

    # functions of a protein
    if g0 and any(k in q for k in ("function", "do ", "does ", "role", "activity")):
        return (
            f"MATCH (p:Protein {{gene_name: {g0}}})-[:HAS_FUNCTION]->(f:Function) "
            "RETURN f.go_id AS go_id, f.name AS function ORDER BY function LIMIT 25",
            "protein_functions",
        )

    # pathways of a protein
    if g0 and any(k in q for k in ("pathway", "process", "involved")):
        return (
            f"MATCH (p:Protein {{gene_name: {g0}}})-[:PARTICIPATES_IN]->(w:Pathway) "
            "RETURN w.name AS pathway ORDER BY pathway LIMIT 25",
            "protein_pathways",
        )

    # hub / most connected proteins
    if any(k in q for k in ("hub", "most connected", "most interact", "highest degree")):
        return (
            "MATCH (p:Protein)-[:INTERACTS_WITH]-() "
            "RETURN p.gene_name AS protein, p.protein_name AS name, count(*) AS degree "
            "ORDER BY degree DESC LIMIT 25",
            "hub_proteins",
        )

    # densest pathway
    if "pathway" in q and any(k in q for k in ("dense", "connected", "most")):
        return (
            "MATCH (w:Pathway)<-[:PARTICIPATES_IN]-(p:Protein) "
            "WITH w, collect(p) AS ps UNWIND ps AS a UNWIND ps AS b "
            "WITH w, a, b WHERE elementId(a) < elementId(b) AND (a)-[:INTERACTS_WITH]-(b) "
            "RETURN w.name AS pathway, count(*) AS internal_edges "
            "ORDER BY internal_edges DESC LIMIT 25",
            "densest_pathway",
        )

    # most abundant proteins
    if "abundant" in q or "abundance" in q:
        return (
            "MATCH (p:Protein) RETURN p.gene_name AS protein, p.protein_name AS name, "
            "p.abundance AS abundance ORDER BY p.abundance_rank LIMIT 25",
            "most_abundant",
        )

    # most common functions
    if "function" in q and any(k in q for k in ("common", "frequent", "most")):
        return (
            "MATCH (p:Protein)-[:HAS_FUNCTION]->(f:Function) "
            "RETURN f.name AS function, count(DISTINCT p) AS n_proteins "
            "ORDER BY n_proteins DESC LIMIT 25",
            "common_functions",
        )

    raise ValueError(
        "The rule-based (template) backend could not map this question. "
        "Try rephrasing, or set LLM_BACKEND=anthropic / ollama for open-ended questions."
    )


# --------------------------------------------------------------------------- #
# Backend: anthropic
# --------------------------------------------------------------------------- #
def anthropic_to_cypher(question: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=C.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=C.ANTHROPIC_MODEL,
        max_tokens=400,
        system=SCHEMA + "\n" + CYPHER_INSTRUCTIONS,
        messages=[{"role": "user", "content": question}],
    )
    return _clean_cypher("".join(b.text for b in msg.content if b.type == "text"))


# --------------------------------------------------------------------------- #
# Backend: ollama (local)
# --------------------------------------------------------------------------- #
def ollama_to_cypher(question: str) -> str:
    resp = requests.post(
        f"{C.OLLAMA_HOST}/api/generate",
        json={
            "model": C.OLLAMA_MODEL,
            "system": SCHEMA + "\n" + CYPHER_INSTRUCTIONS,
            "prompt": question,
            "stream": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return _clean_cypher(resp.json()["response"])


def _clean_cypher(text: str) -> str:
    """Strip markdown fences / stray prose an LLM might add."""
    text = text.strip()
    text = re.sub(r"^```(?:cypher)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def to_cypher(question: str, vocab: set[str]) -> tuple[str, str]:
    """Return (cypher, backend_label)."""
    backend = C.LLM_BACKEND
    if backend == "anthropic":
        if not C.ANTHROPIC_API_KEY:
            raise SystemExit("LLM_BACKEND=anthropic but ANTHROPIC_API_KEY is empty.")
        return anthropic_to_cypher(question), "anthropic:" + C.ANTHROPIC_MODEL
    if backend == "ollama":
        return ollama_to_cypher(question), "ollama:" + C.OLLAMA_MODEL
    # default: template
    cypher, intent = template_to_cypher(question, vocab)
    return cypher, f"template:{intent}"
