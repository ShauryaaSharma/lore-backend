"""The agent loop, driven by a scripted fake model.

No network: the LLM is replaced with a fixed sequence of replies and the
semantic store with in-memory hits. What's being tested is the control flow —
does it stop when it should, does the hop cap hold, does a failing tool kill
the run — not Groq's output.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from app.agent import graph as agent_graph
from app.agent.tools import Collector
from app.config import settings
from app.memory.semantic import Hit


class FakeLLM:
    """Replays a scripted list of AIMessages. Anything past the end repeats
    the last reply, so a runaway-loop test doesn't need an infinite script."""

    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = replies
        self.calls = 0

    def invoke(self, messages):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Keep every test off fastembed, Qdrant, and Groq."""
    monkeypatch.setattr(settings, "rerank_enabled", False)
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(
        "app.memory.semantic.search",
        lambda scope, query, limit=20: [
            Hit(id="pr-482", text="We moved off server-side sessions after a Redis "
                                  "failover logged everyone out.",
                metadata={"source": "PR #482", "repo": "acme/api"}, score=0.9),
        ],
    )
    monkeypatch.setattr("app.memory.episodic.record_query", lambda *a, **k: None)


def run_with(monkeypatch, replies: list[AIMessage], scope: str = "gh:acme"):
    monkeypatch.setattr(agent_graph, "get_llm", lambda tools=None: FakeLLM(replies))
    return agent_graph.run("Why did we drop server-side sessions?", scope)


def test_search_then_answer(monkeypatch):
    result = run_with(monkeypatch, [
        tool_call("search_canon", {"query": "server-side sessions"}),
        AIMessage(content="A Redis failover logged every user out, so we moved to "
                          "short-lived JWTs [PR #482]."),
    ])
    assert result["guardrail"] == "ok"
    assert result["hops"] == 1
    assert result["sources"] == [["PR", "PR #482"]]
    assert result["path"] == "agent"


def test_answering_without_tools_is_allowed_when_it_abstains(monkeypatch):
    """Zero hops is a legitimate outcome — but with nothing retrieved, the
    only shippable answer is an honest one."""
    result = run_with(monkeypatch, [
        AIMessage(content="I don't have a recorded decision for that yet."),
    ])
    assert result["hops"] == 0
    assert result["guardrail"] == "abstain"


def test_uncited_answer_is_replaced_not_shipped(monkeypatch):
    result = run_with(monkeypatch, [
        tool_call("search_canon", {"query": "sessions"}),
        AIMessage(content="You switched because JWTs are more scalable than sessions."),
    ])
    assert result["guardrail"] == "violation"
    assert "couldn't ground an answer" in result["answer"]
    assert result["sources"] == []


def test_hop_cap_stops_a_runaway_loop(monkeypatch):
    """A model that only ever asks for more tools must terminate, and must
    terminate at the configured cap rather than whenever it gives up."""
    monkeypatch.setattr(settings, "agent_max_hops", 3)
    result = run_with(monkeypatch, [tool_call("search_canon", {"query": "again"})])
    assert result["hops"] == 3
    # It never produced prose, so there is nothing to ground: rejected.
    assert result["guardrail"] == "violation"


def test_tool_failure_is_reported_to_the_model_not_raised(monkeypatch):
    """A broken tool should let the agent try something else, not 500."""
    def boom(scope, query, limit=20):
        raise RuntimeError("qdrant is down")

    monkeypatch.setattr("app.memory.semantic.search", boom)
    result = run_with(monkeypatch, [
        tool_call("search_canon", {"query": "sessions"}),
        AIMessage(content="I don't have a recorded decision for that yet."),
    ])
    assert result["guardrail"] == "abstain"
    assert result["hops"] == 1


def test_llm_failure_degrades_to_an_error_answer(monkeypatch):
    class Exploding:
        def invoke(self, messages):
            raise RuntimeError("groq 503")

    monkeypatch.setattr(agent_graph, "get_llm", lambda tools=None: Exploding())
    result = agent_graph.run("Why?", "gh:acme")
    # The node catches it, so the graph still completes and the guardrail
    # turns an empty answer into an honest one.
    assert result["sources"] == []
    assert result["answer"]


def test_scope_is_bound_not_model_controlled(monkeypatch):
    """The model names a query, never a tenant. Whatever it asks for, the
    search must run against the scope resolved from the API key."""
    seen = {}

    def spy(scope, query, limit=20):
        seen["scope"] = scope
        return []

    monkeypatch.setattr("app.memory.semantic.search", spy)
    run_with(monkeypatch, [
        tool_call("search_canon", {"query": "anything"}),
        AIMessage(content="No record of that."),
    ], scope="gh:acme")
    assert seen["scope"] == "gh:acme"


def test_collector_deduplicates_repeated_sources():
    collector = Collector()
    collector.add_hit(source="PR #1", text="a")
    collector.add_hit(source="PR #1", text="a again")
    assert len(collector.hits) == 1
