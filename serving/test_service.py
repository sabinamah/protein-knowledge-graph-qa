"""Tests that run without a live Neo4j or model server.

They exercise the real pipeline code: the rule-based template translation, the
read-only guard, and the OpenAI-compatible backend's request building (mocked).
Run:  pytest -q serving/test_service.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import nl2cypher as nl        # noqa: E402
from ask import is_read_only  # noqa: E402


def test_template_interaction_partners():
    vocab = {"gapA", "pfkA"}
    cypher, intent = nl.template_to_cypher("what does gapA interact with?", vocab)
    assert intent == "interaction_partners"
    assert "INTERACTS_WITH" in cypher
    assert "gapA" in cypher


def test_read_only_guard():
    assert is_read_only("MATCH (p:Protein) RETURN p LIMIT 5")
    assert not is_read_only("MATCH (p) DELETE p")


def test_openai_backend_builds_request(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "MATCH (p) RETURN p LIMIT 1"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(nl.requests, "post", fake_post)
    cypher = nl.openai_compatible_to_cypher("any question")
    assert captured["url"].endswith("/chat/completions")   # OpenAI-compatible path
    assert captured["json"]["messages"][0]["role"] == "system"
    assert cypher == "MATCH (p) RETURN p LIMIT 1"
