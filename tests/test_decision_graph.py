"""The decision graph against real Postgres: whether a decision still holds,
its lineage, and which decisions touched a path."""

from __future__ import annotations

import pytest

from lore_backend.agent.tools import Collector, build_tools
from lore_backend.memory import episodic, graph
from lore_backend.retrieval import canon

SCOPE = "gh:acme"
REPO = "acme/api"


def pr(number: int, body: str = "", *, merged: str | None = "2026-01-01T00:00:00Z",
       title: str | None = None, files: list[str] | None = None, scope: str = SCOPE) -> str:
    """Store a PR the way ingestion does: an episodic event, then its edges."""
    source = f"acme/api#{number}"
    title = title or f"Decision {number}"
    episodic.record_event(scope, kind="pr", source=source, title=title,
                          body=f"PR #{number}: {title}\n\n{body}", repo=REPO,
                          occurred_at=merged)
    graph.index_decision(scope, source, title=title, body=body, repo=REPO,
                         files=None if files is None else [{"filename": f, "status": "modified"}
                                                           for f in files])
    return source


def status(source: str) -> graph.Status:
    return graph.statuses(SCOPE, [source])[source]


# ------------------------------------------------------------------ status

def test_a_decision_nothing_overturned_is_active():
    pr(1)
    assert status("acme/api#1").state == "active"


def test_superseded_names_what_replaced_it_and_why():
    pr(1)
    pr(2, "Supersedes #1 because session failover logged everyone out.")
    found = status("acme/api#1")
    assert (found.state, found.overturned_by) == ("superseded", "acme/api#2")
    assert "failover" in found.evidence


def test_reverted():
    pr(1)
    pr(2, "Reverts acme/api#1")
    assert status("acme/api#1").state == "reverted"


def test_reverting_the_revert_restores_the_original():
    pr(1)
    pr(2, "Reverts acme/api#1", merged="2026-02-01T00:00:00Z")
    pr(3, "Reverts acme/api#2", merged="2026-03-01T00:00:00Z")
    assert status("acme/api#1").state == "active"
    assert status("acme/api#2").state == "reverted"
    assert status("acme/api#3").state == "active"


def test_superseding_the_replacement_does_not_bring_the_original_back():
    """Only a revert undoes. A -> B -> C is a chain of replacements, and A is
    no more current for B having been replaced too."""
    pr(1)
    pr(2, "Supersedes #1", merged="2026-02-01T00:00:00Z")
    pr(3, "Supersedes #2", merged="2026-03-01T00:00:00Z")
    assert status("acme/api#1").overturned_by == "acme/api#2"
    assert status("acme/api#2").overturned_by == "acme/api#3"


def test_a_pr_that_was_never_merged_overturns_nothing():
    """Backfill keeps closed PRs too; an abandoned replacement is not one."""
    pr(1)
    pr(2, "Supersedes #1", merged=None)
    assert status("acme/api#1").state == "active"


def test_a_target_lore_has_not_ingested_is_unknown_not_active():
    pr(2, "Supersedes #1")
    assert status("acme/api#1").state == "unknown"


def test_an_edge_starts_counting_once_its_target_is_ingested():
    pr(2, "Supersedes #1")
    pr(1)
    assert status("acme/api#1").state == "superseded"


def test_a_cycle_terminates_and_leaves_both_in_force():
    pr(1, "Supersedes #2")
    pr(2, "Supersedes #1")
    assert status("acme/api#1").state == "active"
    assert status("acme/api#2").state == "active"


def test_a_longer_cycle_is_ignored_from_every_starting_point():
    pr(1, "Supersedes #3")
    pr(2, "Supersedes #1")
    pr(3, "Supersedes #2")
    pr(4, "Supersedes #1")
    # The 1->3->2->1 loop is ignored; #4's edge into it is not.
    assert {s: status(f"acme/api#{s}").state for s in (1, 2, 3)} == {
        1: "superseded", 2: "active", 3: "active"}
    assert status("acme/api#1").overturned_by == "acme/api#4"


def test_the_newest_live_overturner_is_reported():
    pr(1)
    pr(2, "Supersedes #1", merged="2026-02-01T00:00:00Z")
    pr(3, "Supersedes #1", merged="2026-03-01T00:00:00Z")
    assert status("acme/api#1").overturned_by == "acme/api#3"


def test_scopes_are_isolated():
    pr(1)
    pr(2, "Supersedes #1", scope="gh:other")
    assert status("acme/api#1").state == "active"


# --------------------------------------------------------------- indexing

def test_reindexing_replaces_edges_instead_of_accumulating_them():
    """An edited PR body that drops 'Supersedes #1' must stop overturning #1."""
    pr(1)
    pr(2, "Supersedes #1")
    pr(2, "Unrelated now.")
    assert status("acme/api#1").state == "active"


def test_files_none_keeps_previously_recorded_files():
    pr(1, files=["src/auth/session.py"])
    pr(1)  # redelivered without a GitHub token: files not fetched
    assert [d["source"] for d in graph.decisions_touching(SCOPE, "src/auth/")] == ["acme/api#1"]


def test_files_empty_list_clears_them():
    pr(1, files=["src/auth/session.py"])
    pr(1, files=[])
    assert graph.decisions_touching(SCOPE, "src/auth/") == []


def test_rebuild_indexes_decisions_stored_before_the_graph_existed():
    episodic.record_event(SCOPE, kind="pr", source="acme/api#1", title="Old",
                          body="acme/api#1: Old", repo=REPO, occurred_at="2026-01-01T00:00:00Z")
    episodic.record_event(SCOPE, kind="pr", source="acme/api#2", title="New",
                          body="acme/api#2: New\n\nSupersedes #1\n\nDiscussion:\n[comment] @a: replaces #9?",
                          repo=REPO, occurred_at="2026-02-01T00:00:00Z")

    assert graph.rebuild_links(SCOPE) == {"decisions": 2, "edges": 2}
    assert status("acme/api#1").state == "superseded"
    links = {(r["source"], r["kind"]) for r in graph.decision(SCOPE, "acme/api#2")["links_out"]}
    # The discussion's "replaces #9?" stays a mention: comments do not overturn.
    assert links == {("acme/api#1", "supersedes"), ("acme/api#9", "references")}


def test_inscribe_pr_indexes_links_and_files(monkeypatch):
    monkeypatch.setattr(canon.semantic, "remember", lambda *a, **k: None)
    canon.inscribe_pr(SCOPE, number=1, title="Sessions", body="", threads="", author="a",
                      repo_full=REPO, url="", merged_at="2026-01-01T00:00:00Z")
    canon.inscribe_pr(SCOPE, number=2, title="JWT", body="Supersedes #1", threads="",
                      author="a", repo_full=REPO, url="", merged_at="2026-02-01T00:00:00Z",
                      files=[{"filename": "src/auth/jwt.py", "status": "added"}])

    assert status("acme/api#1").overturned_by == "acme/api#2"
    assert graph.decision(SCOPE, "acme/api#2")["files"] == [{"path": "src/auth/jwt.py",
                                                        "change": "added"}]


def test_inscribe_commit_indexes_its_why(monkeypatch):
    monkeypatch.setattr(canon.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(canon.semantic, "remember", lambda *a, **k: None)
    pr(5)
    canon.inscribe_commit({"hash": "abcdef1234", "message": "Drop sessions", "repo": REPO,
                           "why": "Replaces #5: the session store was a single point of failure"},
                          SCOPE)
    assert graph.decision(SCOPE, "commit abcdef1")["links_out"][0]["source"] == "acme/api#5"


# ------------------------------------------------------------------ reads

def test_lineage_walks_both_directions_with_depth():
    pr(1, merged="2026-01-01T00:00:00Z")
    pr(2, "Supersedes #1", merged="2026-02-01T00:00:00Z")
    pr(3, "Supersedes #2", merged="2026-03-01T00:00:00Z")

    middle = graph.decision(SCOPE, "acme/api#2")
    assert [(d["source"], d["depth"], d["status"]) for d in middle["lineage"]] == [
        ("acme/api#1", 1, "superseded"), ("acme/api#3", 1, "active")]
    assert middle["status"] == "superseded"


def test_max_depth_trims_lineage_but_not_status():
    for n in range(1, 5):
        pr(n, f"Supersedes #{n - 1}" if n > 1 else "", merged=f"2026-0{n}-01T00:00:00Z")
    pr(5, "Reverts acme/api#4", merged="2026-05-01T00:00:00Z")

    first = graph.decision(SCOPE, "acme/api#1", max_depth=1)
    assert [d["source"] for d in first["lineage"]] == ["acme/api#2"]
    # #4 was reverted, so #3 holds again and #1 is still superseded by #2,
    # which #3 superseded: the chain beyond depth 1 still decides status.
    assert first["status"] == "superseded"
    assert graph.decision(SCOPE, "acme/api#3")["status"] == "active"


def test_decision_reports_unresolved_links():
    pr(2, "Supersedes #1. See #30.")
    found = graph.decision(SCOPE, "acme/api#2")
    assert {(r["source"], r["ingested"]) for r in found["links_out"]} == {
        ("acme/api#1", False), ("acme/api#30", False)}


def test_a_decision_known_only_from_an_edge_is_still_found():
    pr(2, "Supersedes #1")
    found = graph.decision(SCOPE, "acme/api#1")
    assert found["ingested"] is False
    assert found["links_in"][0]["source"] == "acme/api#2"


def test_unknown_decision_is_none():
    assert graph.decision(SCOPE, "acme/api#404") is None


def test_files_by_directory_newest_first_with_status():
    pr(1, files=["src/auth/session.py"], merged="2026-01-01T00:00:00Z")
    pr(2, "Supersedes #1", files=["src/auth/jwt.py", "README.md"], merged="2026-02-01T00:00:00Z")
    pr(3, files=["src/billing/invoice.py"])

    found = graph.decisions_touching(SCOPE, "src/auth/")
    assert [(d["source"], d["status"]) for d in found] == [
        ("acme/api#2", "active"), ("acme/api#1", "superseded")]
    assert found[0]["paths"] == ["src/auth/jwt.py"]


@pytest.mark.parametrize("query", ["src/auth", "src/auth/", "/src/auth"])
def test_directory_spellings_agree(query):
    pr(1, files=["src/auth/session.py"])
    assert [d["source"] for d in graph.decisions_touching(SCOPE, query)] == ["acme/api#1"]


def test_exact_file_match():
    pr(1, files=["src/auth.py", "src/auth/session.py"])
    assert graph.decisions_touching(SCOPE, "src/auth.py")[0]["paths"] == ["src/auth.py"]


def test_directory_prefix_does_not_match_a_sibling_with_the_same_start():
    pr(1, files=["src/authz/policy.py"])
    assert graph.decisions_touching(SCOPE, "src/auth") == []


def test_like_wildcards_in_paths_are_literal():
    pr(1, files=["src/a_b/x.py"])
    pr(2, files=["src/aXb/x.py"])
    assert [d["source"] for d in graph.decisions_touching(SCOPE, "src/a_b/")] == ["acme/api#1"]


# ------------------------------------------------------------- agent tools

def tools_by_name(collector: Collector):
    return {t.name: t for t in build_tools(SCOPE, "acme", collector)}


def test_decision_status_tool_reports_the_replacement_and_makes_it_citable():
    pr(1, title="Server sessions")
    pr(2, "Supersedes #1: failover logged everyone out.", title="Move to JWT")
    collector = Collector()

    text = tools_by_name(collector)["decision_status"].invoke({"source": "#1"})

    assert "status: superseded" in text
    assert "overturned by acme/api#2 (Move to JWT)" in text
    assert {h["source"] for h in collector.hits} == {"acme/api#1", "acme/api#2"}


def test_decision_status_tool_does_not_claim_anything_without_a_record():
    collector = Collector()
    text = tools_by_name(collector)["decision_status"].invoke({"source": "acme/api#404"})
    assert "no record" in text
    assert collector.hits == []


def test_decisions_for_path_tool():
    pr(1, files=["src/auth/session.py"], title="Server sessions", merged="2026-01-01T00:00:00Z")
    pr(2, "Supersedes #1", files=["src/auth/jwt.py"], title="Move to JWT",
       merged="2026-02-01T00:00:00Z")
    collector = Collector()

    text = tools_by_name(collector)["decisions_for_path"].invoke({"path": "src/auth/"})

    assert "[acme/api#1] (superseded by acme/api#2) Server sessions" in text
    assert [h["source"] for h in collector.hits] == ["acme/api#2", "acme/api#1"]


# -------------------------------------------------------------------- API

def test_api_decision(client):
    pr(1)
    pr(2, "Supersedes #1")
    response = client.get("/v1/graph/decision", params={"source": "1", "user_id": SCOPE})
    assert response.status_code == 200
    body = response.json()
    assert (body["source"], body["status"], body["overturned_by"]) == (
        "acme/api#1", "superseded", "acme/api#2")


def test_api_decision_unknown_is_404(client):
    response = client.get("/v1/graph/decision", params={"source": "acme/api#404", "user_id": SCOPE})
    assert response.status_code == 404


@pytest.mark.parametrize("params", [{}, {"source": "auth"}, {"source": "1", "depth": 0},
                                    {"source": "1", "depth": 11}])
def test_api_decision_validation(client, params):
    response = client.get("/v1/graph/decision", params={**params, "user_id": SCOPE})
    assert response.status_code == 422


def test_api_files(client):
    pr(1, files=["src/auth/session.py"])
    response = client.get("/v1/graph/files", params={"path": "src/auth/", "user_id": SCOPE})
    assert response.status_code == 200
    assert response.json()["count"] == 1


@pytest.mark.parametrize("params", [{}, {"path": ""}, {"path": "x", "limit": 0},
                                    {"path": "x", "limit": 101}])
def test_api_files_validation(client, params):
    response = client.get("/v1/graph/files", params={**params, "user_id": SCOPE})
    assert response.status_code == 422


def test_api_rebuild(client):
    episodic.record_event(SCOPE, kind="pr", source="acme/api#2", title="New",
                          body="acme/api#2: New\n\nSupersedes #1", repo=REPO)
    response = client.post("/v1/graph/rebuild", params={"user_id": SCOPE})
    assert response.json() == {"decisions": 1, "edges": 1}


def test_api_reads_only_the_callers_scope(client):
    pr(1, scope="gh:other", files=["src/auth/session.py"])
    response = client.get("/v1/graph/files", params={"path": "src/", "user_id": SCOPE})
    assert response.json()["count"] == 0
