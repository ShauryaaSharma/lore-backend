"""Consolidation: episodic events distilled into semantic facts.

Groq and the vector store are both faked — what matters here is the
bookkeeping. A distillation that silently loses events, or one that marks
events done when the model failed, would quietly degrade the Canon.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.memory import consolidate, episodic

SCOPE = "gh:acme"


class FakeGroq:
    """Returns a canned summary, or raises for chosen sources."""

    def __init__(self, fail_for: tuple[str, ...] = ()) -> None:
        self.fail_for = fail_for
        self.calls = 0
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        content = kwargs["messages"][0]["content"]
        if any(f in content for f in self.fail_for):
            raise RuntimeError("groq 500")
        return type("R", (), {"choices": [
            type("C", (), {"message": type("M", (), {"content": "A distilled fact."})()})()
        ]})()


@pytest.fixture
def written(monkeypatch):
    """Capture semantic writes instead of embedding anything."""
    calls = []
    monkeypatch.setattr(
        "app.memory.semantic.remember",
        lambda scope, *, text, source, metadata=None: calls.append(
            {"scope": scope, "text": text, "source": source, "metadata": metadata or {}}),
    )
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    return calls


def _seed(n: int) -> None:
    for i in range(n):
        episodic.record_event(SCOPE, kind="pr", source=f"PR #{i}",
                              title=f"title {i}", body=f"long raw discussion {i}")


def test_consolidation_distils_and_marks_done(written, monkeypatch):
    monkeypatch.setattr("groq.Groq", lambda api_key: FakeGroq())
    _seed(3)

    result = consolidate.consolidate_scope(SCOPE)

    assert result["consolidated"] == 3
    assert len(written) == 3
    assert episodic.pending_count(SCOPE) == 0


def test_distilled_entry_overwrites_the_raw_one(written, monkeypatch):
    """Same `source`, so `remember` updates in place. Otherwise the raw text
    stays in the store next to its own summary and both compete in search."""
    monkeypatch.setattr("groq.Groq", lambda api_key: FakeGroq())
    _seed(1)

    consolidate.consolidate_scope(SCOPE)

    assert written[0]["source"] == "PR #0"
    assert written[0]["text"] == "A distilled fact."
    assert written[0]["metadata"]["distilled"] is True


def test_a_failed_summary_leaves_the_event_pending(written, monkeypatch):
    """Otherwise a transient Groq error silently drops a decision forever."""
    monkeypatch.setattr("groq.Groq", lambda api_key: FakeGroq(fail_for=("title 1",)))
    _seed(3)

    result = consolidate.consolidate_scope(SCOPE)

    assert result["consolidated"] == 2
    assert result["skipped"] == 1
    assert [e["source"] for e in episodic.pending_consolidation(SCOPE, 10)] == ["PR #1"]


def test_mock_mode_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    _seed(2)

    result = consolidate.consolidate_scope(SCOPE)

    assert result["consolidated"] == 0
    assert episodic.pending_count(SCOPE) == 2


def test_nothing_pending_is_a_cheap_no_op(monkeypatch):
    called = []
    monkeypatch.setattr("groq.Groq", lambda api_key: called.append(1))
    assert consolidate.consolidate_scope(SCOPE)["consolidated"] == 0
    assert called == []


def test_due_scopes_uses_the_configured_threshold(monkeypatch):
    monkeypatch.setattr(settings, "consolidate_after_n_events", 3)
    _seed(2)
    assert consolidate.due_scopes() == []
    _seed(4)
    assert consolidate.due_scopes() == [(SCOPE, 4)]
