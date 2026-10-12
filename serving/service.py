"""Shared QA service used by both the REST API and the MCP server.

This wraps the existing pipeline in `src/` (config, nl2cypher, ask) so the
natural-language -> Cypher -> graph -> grounded-answer logic lives in exactly
one place and is reused, not duplicated.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import config as C            # noqa: E402
import nl2cypher as nl        # noqa: E402
from ask import get_vocab, is_read_only, grounded_answer  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402


class QAService:
    """Opens one Neo4j driver and answers questions against the graph."""

    def __init__(self) -> None:
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                C.NEO4J_URI, auth=(C.NEO4J_USER, C.NEO4J_PASSWORD)
            )
        return self._driver

    def answer(self, question: str) -> dict:
        with self.driver.session() as session:
            vocab = get_vocab(session)
            cypher, backend = nl.to_cypher(question, vocab)
            if not is_read_only(cypher):
                raise ValueError("Refusing to run a non-read-only query.")
            rows = [r.data() for r in session.run(cypher)]
            return {
                "question": question,
                "backend": backend,          # which NL->Cypher backend answered
                "cypher": cypher,            # the generated query (for traceability)
                "evidence": rows,            # the exact graph rows the answer uses
                "answer": grounded_answer(question, rows, backend),
            }

    def config_summary(self) -> dict:
        return {
            "neo4j_uri": C.NEO4J_URI,
            "llm_backend": C.LLM_BACKEND,
        }

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
