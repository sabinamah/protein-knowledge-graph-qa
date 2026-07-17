#!/usr/bin/env python3
"""Ask the knowledge graph a natural-language question.

Flow (knowledge-grounded QA):
    question -> Cypher (via nl2cypher backend)
             -> run against Neo4j (read-only)
             -> show the query + retrieved rows as the evidence
             -> a natural-language answer grounded ONLY in those rows.

Every answer is printed next to the exact Cypher and the exact rows it came
from, so the reasoning is fully traceable.

Run:
    python src/ask.py "what does gapA interact with?"
    python src/ask.py            # interactive prompt
"""
import sys
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C
import nl2cypher as nl

WRITE_TOKENS = ("create", "merge", "delete", "set ", "remove", "drop", "detach")


def get_vocab(session) -> set[str]:
    return {r["g"] for r in session.run(
        "MATCH (p:Protein) WHERE p.gene_name IS NOT NULL RETURN p.gene_name AS g")}


def is_read_only(cypher: str) -> bool:
    low = cypher.lower()
    return not any(tok in low for tok in WRITE_TOKENS)


def rows_to_text(rows: list[dict]) -> str:
    if not rows:
        return "(no matching data in the graph)"
    return "\n".join(", ".join(f"{k}={v}" for k, v in r.items()) for r in rows)


def grounded_answer(question: str, rows: list[dict], backend: str) -> str:
    """Turn retrieved rows into prose. Uses the LLM if available, else a
    simple deterministic summary — either way grounded only in `rows`."""
    if not rows:
        return "The graph contains no data matching that question."

    if backend.startswith("anthropic"):
        import anthropic
        client = anthropic.Anthropic(api_key=C.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=C.ANTHROPIC_MODEL,
            max_tokens=400,
            system=(
                "Answer the question using ONLY the graph rows provided. "
                "Do not add outside knowledge. Be concise. If the rows do not "
                "answer it, say so."
            ),
            messages=[{"role": "user",
                       "content": f"Question: {question}\n\nGraph rows:\n{rows_to_text(rows)}"}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()

    # Deterministic fallback: describe the rows.
    cols = list(rows[0].keys())
    n = len(rows)
    lead = f"The graph returned {n} result{'s' if n != 1 else ''}. "
    preview = "; ".join(
        " / ".join(f"{c}: {r[c]}" for c in cols) for r in rows[:5]
    )
    more = "" if n <= 5 else f" (showing first 5 of {n})"
    return lead + preview + more


def answer_one(session, question: str, vocab: set[str]) -> None:
    print(f"\nQ: {question}")
    try:
        cypher, backend = nl.to_cypher(question, vocab)
    except (ValueError, SystemExit) as e:
        print(f"  ! {e}")
        return

    print(f"\n  [backend] {backend}")
    print("  [cypher]")
    for line in cypher.strip().splitlines():
        print("      " + line)

    if not is_read_only(cypher):
        print("  ! refusing to run a non-read-only query")
        return

    rows = [r.data() for r in session.run(cypher)]
    print(f"\n  [evidence] {len(rows)} row(s) retrieved from the graph")
    for r in rows[:10]:
        print("      " + ", ".join(f"{k}={v}" for k, v in r.items()))
    if len(rows) > 10:
        print(f"      ... (+{len(rows) - 10} more)")

    print("\n  [answer]")
    print("      " + grounded_answer(question, rows, backend))


def main() -> None:
    driver = GraphDatabase.driver(C.NEO4J_URI, auth=(C.NEO4J_USER, C.NEO4J_PASSWORD))
    with driver.session() as session:
        vocab = get_vocab(session)
        args = [a for a in sys.argv[1:]]
        if args:
            answer_one(session, " ".join(args), vocab)
        else:
            print("Ask the protein graph a question (blank line to quit).")
            print(f"Backend: {C.LLM_BACKEND}. Known genes: {len(vocab)}.")
            while True:
                try:
                    q = input("\n> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not q:
                    break
                answer_one(session, q, vocab)
    driver.close()


if __name__ == "__main__":
    main()
