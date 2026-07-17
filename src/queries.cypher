// ===========================================================================
// Example Cypher queries over the PaxDB protein knowledge graph.
// Each is a real biological question. Run any of them in the Neo4j Browser
// (http://localhost:7474) or via `python src/run_queries.py`.
// ===========================================================================

// Q1 -- Which proteins share a molecular function with uspA and sit within
//       2 interaction hops of it? (functional + topological neighbourhood)
MATCH (x:Protein {gene_name: 'uspA'})-[:HAS_FUNCTION]->(f:Function)<-[:HAS_FUNCTION]-(other:Protein)
WHERE (x)-[:INTERACTS_WITH*1..2]-(other) AND other <> x
RETURN DISTINCT other.gene_name AS protein, f.name AS shared_function
ORDER BY protein;

// Q2 -- Which pathway has the most densely connected proteins in this subset?
//       (count interaction edges among the proteins of each pathway)
MATCH (w:Pathway)<-[:PARTICIPATES_IN]-(p:Protein)
WITH w, collect(p) AS prots
UNWIND prots AS a
UNWIND prots AS b
WITH w, a, b WHERE elementId(a) < elementId(b) AND (a)-[:INTERACTS_WITH]-(b)
RETURN w.name AS pathway, count(*) AS internal_edges
ORDER BY internal_edges DESC
LIMIT 10;

// Q3 -- Hub proteins: the most connected proteins in the interaction network.
MATCH (p:Protein)-[:INTERACTS_WITH]-()
RETURN p.gene_name AS protein, p.protein_name AS name, count(*) AS degree
ORDER BY degree DESC
LIMIT 10;

// Q4 -- Shortest interaction path between two proteins (rplL and gapA).
MATCH path = shortestPath(
  (a:Protein {gene_name: 'rplL'})-[:INTERACTS_WITH*..6]-(b:Protein {gene_name: 'gapA'})
)
RETURN [n IN nodes(path) | n.gene_name] AS hops, length(path) AS distance;

// Q5 -- Functional partners: proteins that both interact AND share a function
//       (stronger evidence of a real functional relationship).
MATCH (a:Protein)-[:INTERACTS_WITH]-(b:Protein)
WHERE a.string_id < b.string_id
MATCH (a)-[:HAS_FUNCTION]->(f:Function)<-[:HAS_FUNCTION]-(b)
RETURN a.gene_name AS protein_a, b.gene_name AS protein_b, f.name AS shared_function
ORDER BY protein_a
LIMIT 15;

// Q6 -- Most common molecular functions among the most abundant proteins.
MATCH (p:Protein)-[:HAS_FUNCTION]->(f:Function)
RETURN f.name AS function, count(DISTINCT p) AS n_proteins
ORDER BY n_proteins DESC
LIMIT 10;
