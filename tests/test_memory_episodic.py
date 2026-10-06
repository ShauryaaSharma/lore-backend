"""Episodic memory: the tier that exists because vector search can't answer
"what did we decide last month"."""

from __future__ import annotations

from lore_backend.memory import episodic

SCOPE = "gh:acme"


def _event(source: str, occurred_at: str | None = None, **kw):
    return episodic.record_event(
        SCOPE, kind="pr", source=source, title=kw.pop("title", source),
        body=kw.pop("body", "decision body"), occurred_at=occurred_at, **kw)


def test_recent_orders_by_when_it_happened_not_when_we_ingested():
    """The whole point of this tier. The oldest PR is inserted last, and
    must still come back last."""
    _event("PR #1", "2026-01-01T00:00:00Z")
    _event("PR #3", "2026-03-01T00:00:00Z")
    _event("PR #2", "2026-02-01T00:00:00Z")

    sources = [e["source"] for e in episodic.recent(SCOPE, limit=5)]
    assert sources == ["PR #3", "PR #2", "PR #1"]


def test_reingesting_a_pr_updates_it_rather_than_duplicating():
    """A redelivered webhook must not create a second decision."""
    _event("PR #7", "2026-01-01T00:00:00Z", title="first title")
    _event("PR #7", "2026-01-01T00:00:00Z", title="edited title")

    events = episodic.recent(SCOPE, limit=10)
    assert len(events) == 1
    assert events[0]["title"] == "edited title"


def test_reingesting_resets_consolidation():
    """An edited PR body needs distilling again — otherwise the semantic
    entry keeps describing the version we first saw."""
    _event("PR #7")
    episodic.mark_consolidated(SCOPE, ["PR #7"])
    assert episodic.pending_count(SCOPE) == 0

    _event("PR #7", title="body changed")
    assert episodic.pending_count(SCOPE) == 1


def test_scopes_are_isolated():
    _event("PR #1")
    episodic.record_event("gh:other", kind="pr", source="PR #1", title="theirs")

    ours = episodic.recent(SCOPE, limit=10)
    assert len(ours) == 1
    assert ours[0]["title"] == "PR #1"


def test_pending_consolidation_only_returns_undistilled_events():
    _event("PR #1")
    _event("PR #2")
    episodic.mark_consolidated(SCOPE, ["PR #1"])

    pending = [e["source"] for e in episodic.pending_consolidation(SCOPE, 10)]
    assert pending == ["PR #2"]


def test_scopes_with_pending_respects_the_threshold():
    for i in range(3):
        _event(f"PR #{i}")
    assert episodic.scopes_with_pending(5) == []
    assert episodic.scopes_with_pending(3) == [(SCOPE, 3)]


def test_since_days_filters_out_old_decisions():
    _event("PR #old", "2020-01-01T00:00:00Z")
    _event("PR #new", "2026-08-19T00:00:00Z")
    recent = [e["source"] for e in episodic.recent(SCOPE, limit=10, since_days=30)]
    assert recent == ["PR #new"]


def test_record_query_round_trips():
    episodic.record_query(SCOPE, question="why jwts?", answer="because [PR #482]",
                          sources=[["PR", "PR #482"]], hops=2, latency_ms=1200,
                          trace_id="abc123", path="agent")
    queries = episodic.recent_queries(SCOPE)
    assert len(queries) == 1
    assert queries[0]["hops"] == 2
    assert queries[0]["path"] == "agent"


def test_record_query_never_raises_into_the_caller():
    """A logging failure must not fail a /why that already succeeded."""
    import lore_backend.memory.episodic as mod

    original = mod.get_conn
    mod.get_conn = lambda: (_ for _ in ()).throw(RuntimeError("db gone"))
    try:
        episodic.record_query(SCOPE, question="q", answer="a", sources=[])
    finally:
        mod.get_conn = original
