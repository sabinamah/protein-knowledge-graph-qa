#!/usr/bin/env python3
"""Build the knowledge-graph tables from PaxDB + STRING + UniProt.

Pipeline
--------
1. Take the TOP_N most-abundant proteins for the target organism from the
   existing PaxDB abundance CSV (produced by the ~/RWTH pipeline).
2. INTERACTS_WITH: download STRING's protein.links file for the organism and
   keep high-confidence edges *within* the subset. STRING ids are identical to
   PaxDB `string_id` (e.g. 511145.b3495), so no id translation is needed.
3. HAS_FUNCTION + PARTICIPATES_IN: map STRING ids -> UniProt and pull GO
   molecular-function terms and curated pathway names.

Outputs (written to data/):
    proteins.csv       one row per protein node
    interactions.csv   protein--protein edges (INTERACTS_WITH)
    functions.csv      protein--GO-term edges (HAS_FUNCTION)
    pathways.csv       protein--pathway edges (PARTICIPATES_IN)

Run:
    python src/build_dataset.py
"""
import gzip
import io
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C

STRING_VERSION = "v12.0"
STRING_LINKS_URL = (
    "https://stringdb-downloads.org/download/protein.links.{v}/"
    "{taxid}.protein.links.{v}.txt.gz"
)
UNIPROT_IDMAP = "https://rest.uniprot.org/idmapping"
UNIPROT_FIELDS = "accession,protein_name,go_f,cc_pathway"


# --------------------------------------------------------------------------- #
# 1. Protein subset from PaxDB
# --------------------------------------------------------------------------- #
def load_protein_subset() -> pd.DataFrame:
    src = Path(C.PAXDB_SOURCE_CSV)
    if not src.exists():
        raise SystemExit(
            f"PaxDB source not found: {src}\n"
            f"Point PAXDB_SOURCE_CSV at a *_abundance.csv from the RWTH pipeline."
        )
    df = pd.read_csv(src)
    df = df.sort_values("abundance_rank").head(C.TOP_N).reset_index(drop=True)
    cols = ["string_id", "gene_name", "abundance", "abundance_rank", "abundance_percent"]
    df = df[[c for c in cols if c in df.columns]].copy()
    print(f"[paxdb] top {len(df)} proteins for taxid {C.TAXID}")
    return df


# --------------------------------------------------------------------------- #
# 2. STRING interactions within the subset
# --------------------------------------------------------------------------- #
def build_interactions(string_ids: set[str]) -> pd.DataFrame:
    C.RAW_DIR.mkdir(parents=True, exist_ok=True)
    local = C.RAW_DIR / f"{C.TAXID}.protein.links.{STRING_VERSION}.txt.gz"
    if not local.exists():
        url = STRING_LINKS_URL.format(v=STRING_VERSION, taxid=C.TAXID)
        print(f"[string] downloading {url}")
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        local.write_bytes(resp.content)
    print(f"[string] parsing {local.name}")

    with gzip.open(local, "rt") as fh:
        df = pd.read_csv(fh, sep=" ")
    # Columns: protein1 protein2 combined_score
    df = df[
        df["protein1"].isin(string_ids)
        & df["protein2"].isin(string_ids)
        & (df["combined_score"] >= C.STRING_SCORE_MIN)
    ].copy()
    # STRING lists each undirected pair twice (a,b and b,a). Keep one.
    df["pair"] = df.apply(
        lambda r: tuple(sorted((r["protein1"], r["protein2"]))), axis=1
    )
    df = df.drop_duplicates("pair").drop(columns="pair")
    df = df.rename(columns={"protein1": "source", "protein2": "target"})
    df["score"] = (df["combined_score"] / 1000).round(3)
    out = df[["source", "target", "score"]].reset_index(drop=True)
    print(f"[string] {len(out)} high-confidence edges (score >= {C.STRING_SCORE_MIN})")
    return out


# --------------------------------------------------------------------------- #
# 3. UniProt annotation (GO molecular function + pathways)
# --------------------------------------------------------------------------- #
def _uniprot_map(string_ids: list[str]) -> pd.DataFrame:
    print(f"[uniprot] submitting id-mapping job for {len(string_ids)} ids")
    run = requests.post(
        f"{UNIPROT_IDMAP}/run",
        data={"from": "STRING", "to": "UniProtKB", "ids": ",".join(string_ids)},
        timeout=60,
    )
    run.raise_for_status()
    job = run.json()["jobId"]

    deadline = time.time() + 180
    while time.time() < deadline:
        st = requests.get(
            f"{UNIPROT_IDMAP}/status/{job}", timeout=60, allow_redirects=False
        )
        if st.status_code in (301, 302, 303):
            break
        if st.json().get("jobStatus") == "FINISHED":
            break
        time.sleep(3)

    url = (
        f"{UNIPROT_IDMAP}/uniprotkb/results/{job}"
        f"?fields={UNIPROT_FIELDS}&format=tsv&size=500"
    )
    frames = []
    while url:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        if resp.text.strip():
            frames.append(pd.read_csv(io.StringIO(resp.text), sep="\t"))
        url = resp.links.get("next", {}).get("url")
    if not frames:
        return pd.DataFrame()
    ann = pd.concat(frames, ignore_index=True).rename(
        columns={
            "From": "string_id",
            "Entry": "uniprot",
            "Protein names": "protein_name",
            "Gene Ontology (molecular function)": "go_mf",
            "Pathway": "pathway",
        }
    )
    # One UniProt hit per STRING id (the first / reviewed-ish).
    return ann.drop_duplicates("string_id")


# "Name of term [GO:0003824]" -> ("GO:0003824", "Name of term")
_GO_RE = re.compile(r"\s*(.+?)\s*\[(GO:\d+)\]")


def parse_functions(ann: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in ann.iterrows():
        text = r.get("go_mf")
        if not isinstance(text, str):
            continue
        for term in text.split(";"):
            m = _GO_RE.search(term)
            if m:
                rows.append(
                    {"string_id": r["string_id"], "go_id": m.group(2),
                     "go_name": m.group(1)}
                )
    out = pd.DataFrame(rows).drop_duplicates()
    print(f"[uniprot] {len(out)} protein->function edges, "
          f"{out['go_id'].nunique() if len(out) else 0} distinct GO terms")
    return out


def parse_pathways(ann: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in ann.iterrows():
        text = r.get("pathway")
        if not isinstance(text, str):
            continue
        # UniProt "Pathway" is free text like:
        #   "Amino-acid biosynthesis; L-threonine biosynthesis."
        # Take the most specific clause as the pathway name.
        clean = text.replace("PATHWAY:", "").strip().rstrip(".")
        for clause in clean.split("; "):
            name = clause.strip().rstrip(".")
            if name:
                rows.append({"string_id": r["string_id"], "pathway": name})
    out = pd.DataFrame(rows).drop_duplicates()
    print(f"[uniprot] {len(out)} protein->pathway edges, "
          f"{out['pathway'].nunique() if len(out) else 0} distinct pathways")
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    proteins = load_protein_subset()
    ids = proteins["string_id"].tolist()

    interactions = build_interactions(set(ids))

    ann = _uniprot_map(ids)
    if not ann.empty:
        # Enrich protein nodes with UniProt accession + protein name.
        proteins = proteins.merge(
            ann[["string_id", "uniprot", "protein_name"]], on="string_id", how="left"
        )
    functions = parse_functions(ann)
    pathways = parse_pathways(ann)

    proteins.to_csv(C.DATA_DIR / "proteins.csv", index=False)
    interactions.to_csv(C.DATA_DIR / "interactions.csv", index=False)
    functions.to_csv(C.DATA_DIR / "functions.csv", index=False)
    pathways.to_csv(C.DATA_DIR / "pathways.csv", index=False)
    print(f"\n[done] wrote 4 tables to {C.DATA_DIR}")


if __name__ == "__main__":
    main()
