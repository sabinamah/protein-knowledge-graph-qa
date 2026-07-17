#!/usr/bin/env python3
"""Load the built CSV tables into Neo4j as a property graph.

Schema
------
Nodes:
    (:Protein {string_id, gene_name, abundance, abundance_rank, uniprot, protein_name})
    (:Function {go_id, name})          # GO molecular-function terms
    (:Pathway {name})                  # curated UniProt pathway names

Relationships:
    (:Protein)-[:INTERACTS_WITH {score}]->(:Protein)   # STRING, undirected in meaning
    (:Protein)-[:HAS_FUNCTION]->(:Function)
    (:Protein)-[:PARTICIPATES_IN]->(:Pathway)

The load is idempotent (MERGE), so re-running is safe.

Run:
    python src/load_graph.py            # wipe + load
    python src/load_graph.py --keep     # load without wiping first
"""
import sys
from pathlib import Path

import pandas as pd
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C

CONSTRAINTS = [
    "CREATE CONSTRAINT protein_id IF NOT EXISTS FOR (p:Protein) REQUIRE p.string_id IS UNIQUE",
    "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (f:Function) REQUIRE f.go_id IS UNIQUE",
    "CREATE CONSTRAINT pathway_name IF NOT EXISTS FOR (w:Pathway) REQUIRE w.name IS UNIQUE",
]


def load(session, wipe: bool) -> None:
    if wipe:
        print("[neo4j] wiping existing graph")
        session.run("MATCH (n) DETACH DELETE n")
    for c in CONSTRAINTS:
        session.run(c)

    data = C.DATA_DIR
    proteins = pd.read_csv(data / "proteins.csv").where(lambda d: d.notna(), None)
    interactions = pd.read_csv(data / "interactions.csv")
    functions = pd.read_csv(data / "functions.csv")
    pathways = pd.read_csv(data / "pathways.csv")

    print(f"[neo4j] loading {len(proteins)} proteins")
    session.run(
        """
        UNWIND $rows AS r
        MERGE (p:Protein {string_id: r.string_id})
        SET p.gene_name = r.gene_name,
            p.abundance = r.abundance,
            p.abundance_rank = r.abundance_rank,
            p.abundance_percent = r.abundance_percent,
            p.uniprot = r.uniprot,
            p.protein_name = r.protein_name
        """,
        rows=proteins.to_dict("records"),
    )

    print(f"[neo4j] loading {len(functions)} HAS_FUNCTION edges")
    session.run(
        """
        UNWIND $rows AS r
        MERGE (f:Function {go_id: r.go_id})
          SET f.name = r.go_name
        WITH r, f
        MATCH (p:Protein {string_id: r.string_id})
        MERGE (p)-[:HAS_FUNCTION]->(f)
        """,
        rows=functions.to_dict("records"),
    )

    print(f"[neo4j] loading {len(pathways)} PARTICIPATES_IN edges")
    session.run(
        """
        UNWIND $rows AS r
        MERGE (w:Pathway {name: r.pathway})
        WITH r, w
        MATCH (p:Protein {string_id: r.string_id})
        MERGE (p)-[:PARTICIPATES_IN]->(w)
        """,
        rows=pathways.to_dict("records"),
    )

    print(f"[neo4j] loading {len(interactions)} INTERACTS_WITH edges")
    session.run(
        """
        UNWIND $rows AS r
        MATCH (a:Protein {string_id: r.source})
        MATCH (b:Protein {string_id: r.target})
        MERGE (a)-[e:INTERACTS_WITH]->(b)
          SET e.score = r.score
        """,
        rows=interactions.to_dict("records"),
    )


def summary(session) -> None:
    print("\n[neo4j] graph summary")
    for label in ("Protein", "Function", "Pathway"):
        n = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
        print(f"    {label:<10} nodes: {n}")
    for rel in ("INTERACTS_WITH", "HAS_FUNCTION", "PARTICIPATES_IN"):
        n = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c").single()["c"]
        print(f"    {rel:<16} edges: {n}")


def main() -> None:
    wipe = "--keep" not in sys.argv
    driver = GraphDatabase.driver(C.NEO4J_URI, auth=(C.NEO4J_USER, C.NEO4J_PASSWORD))
    with driver.session() as session:
        load(session, wipe=wipe)
        summary(session)
    driver.close()
    print("\n[done] graph loaded. Browse it at http://localhost:7474")


if __name__ == "__main__":
    main()
