#!/usr/bin/env python3
"""Run the example Cypher queries and print their results as tables.

Run:
    python src/run_queries.py
"""
import sys
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C

QUERIES = [
    ("Proteins that share a function with uspA and are within 2 interaction hops",
     """
     MATCH (x:Protein {gene_name: 'uspA'})-[:HAS_FUNCTION]->(f:Function)<-[:HAS_FUNCTION]-(other:Protein)
     WHERE (x)-[:INTERACTS_WITH*1..2]-(other) AND other <> x
     RETURN DISTINCT other.gene_name AS protein, f.name AS shared_function
     ORDER BY protein
     """),
    ("Pathways with the most densely connected proteins",
     """
     MATCH (w:Pathway)<-[:PARTICIPATES_IN]-(p:Protein)
     WITH w, collect(p) AS prots
     UNWIND prots AS a
     UNWIND prots AS b
     WITH w, a, b WHERE elementId(a) < elementId(b) AND (a)-[:INTERACTS_WITH]-(b)
     RETURN w.name AS pathway, count(*) AS internal_edges
     ORDER BY internal_edges DESC LIMIT 10
     """),
    ("Hub proteins (highest interaction degree)",
     """
     MATCH (p:Protein)-[:INTERACTS_WITH]-()
     RETURN p.gene_name AS protein, p.protein_name AS name, count(*) AS degree
     ORDER BY degree DESC LIMIT 10
     """),
    ("Shortest interaction path between rplL and gapA",
     """
     MATCH path = shortestPath(
       (a:Protein {gene_name: 'rplL'})-[:INTERACTS_WITH*..6]-(b:Protein {gene_name: 'gapA'}))
     RETURN [n IN nodes(path) | n.gene_name] AS hops, length(path) AS distance
     """),
    ("Interacting protein pairs that also share a function",
     """
     MATCH (a:Protein)-[:INTERACTS_WITH]-(b:Protein)
     WHERE a.string_id < b.string_id
     MATCH (a)-[:HAS_FUNCTION]->(f:Function)<-[:HAS_FUNCTION]-(b)
     RETURN a.gene_name AS protein_a, b.gene_name AS protein_b, f.name AS shared_function
     ORDER BY protein_a LIMIT 15
     """),
    ("Most common molecular functions among abundant proteins",
     """
     MATCH (p:Protein)-[:HAS_FUNCTION]->(f:Function)
     RETURN f.name AS function, count(DISTINCT p) AS n_proteins
     ORDER BY n_proteins DESC LIMIT 10
     """),
]


def print_table(records) -> None:
    rows = [r.data() for r in records]
    if not rows:
        print("    (no results)")
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print("    " + header)
    print("    " + "  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("    " + "  ".join(str(r[c]).ljust(widths[c]) for c in cols))


def main() -> None:
    driver = GraphDatabase.driver(C.NEO4J_URI, auth=(C.NEO4J_USER, C.NEO4J_PASSWORD))
    with driver.session() as session:
        for i, (title, cypher) in enumerate(QUERIES, 1):
            print(f"\n=== Q{i}. {title} ===")
            print_table(list(session.run(cypher)))
    driver.close()


if __name__ == "__main__":
    main()
