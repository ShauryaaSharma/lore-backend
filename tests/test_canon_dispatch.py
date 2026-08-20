"""`answer_why` picks a path and records the run. These tests cover the
dispatch and the bookkeeping around it — the paths themselves are tested in
test_agent_graph.py and the eval harness."""

from __future__ import annotations

import pytest

from app.config import settings
from app.memory import episodic
from app.memory.semantic import Hit
from app.retrieval import canon

SCOPE = "gh:acme"


def test_mock_mode_answers_from_the_seed_corpus():
    result = canon.answer_why("Why did we move away from server-side sessions?", SCOPE)
    assert result["path"] == "mock"
    assert "#482" in str(result["sources"])


def test_every_path_records_the_question():
    """Including mock — the questions that fail are where the next ingestion
    gap is, and that's as true in a demo as in production."""
    canon.answer_why("Why Postgres instead of Mongo?", SCOPE)
    queries = episodic.recent_queries(SCOPE)
    assert len(queries) == 1
    assert queries[0]["path"] == "mock"


def test_blank_question_short_circuits_without_recording():
    canon.answer_why("   ", SCOPE)
    assert episodic.recent_queries(SCOPE) == []


def test_live_mode_dispatches_to_the_agent_loop(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "agent_loop_enabled", True)
    called = {}

    def fake_run(question, scope, **kwargs):
        called["question"] = question
        return {"answer": "grounded [PR #1]", "sources": [["PR", "PR #1"]],
                "mode": "live", "path": "agent", "hops": 2,
                "trace_id": "t1", "latency_s": 0.4}

    monkeypatch.setattr("app.agent.graph.run", fake_run)

    result = canon.answer_why("why?", SCOPE)

    assert called["question"] == "why?"
    assert result["path"] == "agent"
    recorded = episodic.recent_queries(SCOPE)[0]
    assert recorded["hops"] == 2
    assert recorded["path"] == "agent"


def test_the_flag_falls_back_to_the_v1_pipeline(monkeypatch):
    """The fallback has to stay reachable — it's the baseline the loop is
    measured against."""
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "agent_loop_enabled", False)
    monkeypatch.setattr(settings, "rerank_enabled", False)
    monkeypatch.setattr("app.memory.semantic.search", lambda *a, **k: [])

    result = canon.answer_why("why?", SCOPE)

    assert result["path"] == "pipeline"
    assert result["sources"] == []


def test_pipeline_applies_the_same_guardrail_as_the_agent(monkeypatch):
    """An uncited answer isn't more shippable because a different path
    produced it."""
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "agent_loop_enabled", False)
    monkeypatch.setattr(settings, "rerank_enabled", False)
    monkeypatch.setattr(
        "app.memory.semantic.search",
        lambda *a, **k: [Hit(id="pr-1", text="a real decision",
                             metadata={"source": "PR #1"}, score=0.9)],
    )

    class FakeGroq:
        def __init__(self, api_key): self.chat = self
        @property
        def completions(self): return self
        def create(self, **kw):
            return type("R", (), {"choices": [type("C", (), {
                "message": type("M", (), {"content": "JWTs scale better."})()})()]})()

    monkeypatch.setattr("groq.Groq", FakeGroq)

    result = canon.answer_why("why jwts?", SCOPE)

    assert result["guardrail"] == "violation"
    assert result["sources"] == []


@pytest.mark.parametrize("agent_enabled,expected", [(True, "agent"), (False, "pipeline")])
def test_status_reports_the_active_path(monkeypatch, agent_enabled, expected):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(settings, "agent_loop_enabled", agent_enabled)
    assert canon.status()["path"] == expected
