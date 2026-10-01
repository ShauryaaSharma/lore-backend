"""The decision check: which decisions a reviewer sees on an opened PR."""

from __future__ import annotations

import pytest

from lore_backend.config import settings
from lore_backend.ingestion import github_client as gh
from lore_backend.ingestion import webhook_handler
from lore_backend.memory import episodic, graph
from lore_backend.retrieval import decision_check

SCOPE = "gh:acme"
REPO = "acme/api"


def decision(number: int, files: list[str], body: str = "", *,
             merged: str | None = "2026-01-01T00:00:00Z", title: str | None = None,
             scope: str = SCOPE) -> None:
    source = f"PR #{number}"
    title = title or f"Decision {number}"
    episodic.record_event(scope, kind="pr", source=source, title=title,
                          body=f"{source}: {title}" + (f"\n\n{body}" if body else ""),
                          repo=REPO, occurred_at=merged)
    graph.index_decision(scope, source, title=title, body=body, repo=REPO,
                         files=[{"filename": f, "status": "modified"} for f in files])


def sources(result: dict) -> list[str]:
    return [d["source"] for d in result["decisions"]]


# ---------------------------------------------------------------- matching

def test_same_file_ranks_above_same_directory():
    decision(1, ["src/auth/session.py"], merged="2026-03-01T00:00:00Z")
    decision(2, ["src/auth/jwt.py"], merged="2026-01-01T00:00:00Z")

    result = decision_check.check(SCOPE, ["src/auth/jwt.py"])

    assert sources(result) == ["PR #2", "PR #1"]
    assert [d["match"] for d in result["decisions"]] == ["file", "directory"]


def test_more_overlapping_files_rank_higher():
    decision(1, ["src/a.py"], merged="2026-03-01T00:00:00Z")
    decision(2, ["src/a.py", "src/b.py"], merged="2026-01-01T00:00:00Z")
    assert sources(decision_check.check(SCOPE, ["src/a.py", "src/b.py"])) == ["PR #2", "PR #1"]


def test_recency_breaks_ties():
    decision(1, ["src/a.py"], merged="2026-01-01T00:00:00Z")
    decision(2, ["src/a.py"], merged="2026-02-01T00:00:00Z")
    assert sources(decision_check.check(SCOPE, ["src/a.py"])) == ["PR #2", "PR #1"]


def test_root_level_files_only_match_exactly():
    """Editing README.md is not related to every other root file's decision."""
    decision(1, ["setup.cfg"])
    decision(2, ["README.md"])
    assert sources(decision_check.check(SCOPE, ["README.md"])) == ["PR #2"]


def test_unrelated_directories_do_not_match():
    decision(1, ["src/billing/invoice.py"])
    assert decision_check.check(SCOPE, ["src/auth/jwt.py"])["decisions"] == []


def test_overturned_decisions_are_left_out_but_counted():
    decision(1, ["src/auth/session.py"])
    decision(2, ["src/auth/jwt.py"], "Supersedes #1", merged="2026-02-01T00:00:00Z")

    result = decision_check.check(SCOPE, ["src/auth/session.py"])

    assert sources(result) == ["PR #2"]
    assert result["overturned"] == 1


def test_unmerged_prs_are_not_decisions():
    decision(1, ["src/a.py"], merged=None)
    assert decision_check.check(SCOPE, ["src/a.py"])["decisions"] == []


def test_the_change_is_never_reported_against_itself():
    decision(7, ["src/a.py"])
    assert decision_check.check(SCOPE, ["src/a.py"], number=7)["decisions"] == []


def test_limit():
    for n in range(1, 8):
        decision(n, ["src/a.py"], merged=f"2026-01-0{n}T00:00:00Z")
    assert sources(decision_check.check(SCOPE, ["src/a.py"], limit=3)) == [
        "PR #7", "PR #6", "PR #5"]


def test_scopes_are_isolated():
    decision(1, ["src/a.py"], scope="gh:other")
    assert decision_check.check(SCOPE, ["src/a.py"])["decisions"] == []


def test_no_files_no_query():
    assert decision_check.check(SCOPE, []) == {"files": 0, "decisions": [], "overturned": 0}


def test_summary_is_the_reasoning_not_the_header():
    decision(1, ["src/a.py"], "Session failover logged everyone out.\n\nMore detail here.")
    [found] = decision_check.check(SCOPE, ["src/a.py"])["decisions"]
    assert found["summary"] == "Session failover logged everyone out."


def test_summary_is_empty_without_a_description():
    decision(1, ["src/a.py"])
    assert decision_check.check(SCOPE, ["src/a.py"])["decisions"][0]["summary"] == ""


def test_marks_decisions_the_change_says_it_overturns():
    decision(1, ["src/a.py"])
    decision(2, ["src/a.py"])
    result = decision_check.check(SCOPE, ["src/a.py"], body="Supersedes #1. Context in #2.",
                                  repo=REPO, number=9)
    assert {d["source"]: d["declared"] for d in result["decisions"]} == {
        "PR #1": "supersedes", "PR #2": None}


# --------------------------------------------------------------- rendering

def test_render_is_empty_when_there_is_nothing_to_say():
    assert decision_check.render({"decisions": [], "overturned": 2}) == ""


def test_render():
    decision(1, ["src/auth/session.py"], "Session failover logged everyone out.",
             title="Move to JWT")
    result = decision_check.check(SCOPE, ["src/auth/session.py"], body="Reverts acme/api#1",
                                  repo=REPO, number=9)
    text = decision_check.render(result)

    assert text.splitlines()[2:4] == [
        "- **PR #1** — Move to JWT _(merged 2026-01-01)_ · same file `src/auth/session.py`"
        " · **this PR says it reverts it**",
        "  > Session failover logged everyone out.",
    ]


def test_render_truncates_long_path_lists():
    decision(1, [f"src/m{i}.py" for i in range(6)])
    text = decision_check.render(decision_check.check(SCOPE, [f"src/m{i}.py" for i in range(6)]))
    assert "+2 more" in text


# ----------------------------------------------------------------- webhook

@pytest.fixture
def github(monkeypatch):
    """A live-mode webhook with GitHub faked at the client boundary."""
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(webhook_handler, "pr_understanding_comment",
                        lambda title, body, threads: "## Lore\n\nsummary")
    monkeypatch.setattr(gh, "app_configured", lambda: True)
    monkeypatch.setattr(gh, "installation_token", lambda installation_id: "token")
    monkeypatch.setattr(gh, "fetch_pr_threads", lambda *a, **k: "")
    state = {"files": [], "posted": []}
    monkeypatch.setattr(gh, "fetch_pr_files", lambda *a, **k: [
        {"filename": f, "status": "modified", "additions": 1, "deletions": 0}
        for f in state["files"]])
    monkeypatch.setattr(gh, "post_issue_comment",
                        lambda token, owner, repo, number, body: state["posted"].append(body) or True)
    return state


def opened(number: int = 9, body: str = "") -> dict:
    return {"action": "opened", "installation": {"id": 1},
            "repository": {"full_name": REPO},
            "pull_request": {"number": number, "title": "Rework auth", "body": body,
                             "user": {"login": "dev"}, "html_url": ""}}


def test_webhook_appends_the_decisions_to_the_summary_comment(github):
    decision(1, ["src/auth/session.py"], title="Move to JWT")
    github["files"] = ["src/auth/session.py"]

    result = webhook_handler.handle_pull_request_event(opened())

    assert result["decisions"] == ["PR #1"]
    [comment] = github["posted"]
    assert comment.startswith("## Lore\n\nsummary\n\n**Decisions behind the code")
    assert "**PR #1** — Move to JWT" in comment


def test_webhook_posts_only_the_summary_when_nothing_matches(github):
    github["files"] = ["src/new_feature.py"]
    webhook_handler.handle_pull_request_event(opened())
    assert github["posted"] == ["## Lore\n\nsummary"]


def test_webhook_check_can_be_switched_off(github, monkeypatch):
    monkeypatch.setattr(settings, "pr_decision_check_enabled", False)
    decision(1, ["src/auth/session.py"])
    github["files"] = ["src/auth/session.py"]

    result = webhook_handler.handle_pull_request_event(opened())

    assert result["decisions"] == []
    assert github["posted"] == ["## Lore\n\nsummary"]


# --------------------------------------------------------------------- API

def test_api_check(client):
    decision(1, ["src/auth/session.py"])
    response = client.post("/v1/graph/check", params={"user_id": SCOPE},
                           json={"files": ["src/auth/session.py"], "body": "Supersedes #1",
                                 "repo": REPO})
    assert response.status_code == 200
    body = response.json()
    assert body["files"] == 1
    assert body["decisions"][0]["declared"] == "supersedes"


@pytest.mark.parametrize("payload", [{}, {"files": []}, {"files": ["a"] * 501},
                                     {"files": ["a"], "limit": 0}, {"files": ["a"], "limit": 21}])
def test_api_check_validation(client, payload):
    response = client.post("/v1/graph/check", params={"user_id": SCOPE}, json=payload)
    assert response.status_code == 422
