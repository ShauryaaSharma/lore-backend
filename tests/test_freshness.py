"""Stale-decision warnings: when a decision nobody overturned is probably no
longer how the code works.

This is the one inference in the graph, so most of these tests pin what
must *not* flag a decision -- a false "possibly outdated" teaches people to
ignore the warning."""

from __future__ import annotations

import pytest

from lore_backend.agent.tools import Collector, build_tools
from lore_backend.config import settings
from lore_backend.memory import episodic, graph
from lore_backend.memory.freshness import freshness
from lore_backend.retrieval import decision_check

SCOPE = "gh:acme"
REPO = "acme/api"


def pr(number: int, files: dict[str, str] | list[str], body: str = "", *,
       merged: str | None, title: str | None = None, scope: str = SCOPE) -> str:
    """A merged PR and the files it changed ({path: change} or [path])."""
    source = f"{REPO}#{number}"
    title = title or f"Decision {number}"
    if isinstance(files, list):
        files = {f: "modified" for f in files}
    episodic.record_event(scope, kind="pr", source=source, title=title,
                          body=f"PR #{number}: {title}\n\n{body}", repo=REPO, occurred_at=merged)
    graph.index_decision(scope, source, title=title, body=body, repo=REPO,
                         files=[{"filename": f, "status": c} for f, c in files.items()])
    return source


def state(source: str) -> str:
    return freshness(SCOPE, [source])[source].state


JAN, FEB, MAR, APR = (f"2026-0{m}-01T00:00:00Z" for m in (1, 2, 3, 4))
AUTH = ["src/auth/session.py", "src/auth/cookies.py"]


# ------------------------------------------------------------------ signals

def test_untouched_since_is_current():
    pr(1, AUTH, merged=JAN)
    assert state(f"{REPO}#1") == "current"


def test_churn_by_two_later_prs_flags_it():
    pr(1, AUTH, merged=JAN)
    pr(2, ["src/auth/session.py"], merged=FEB)
    pr(3, ["src/auth/cookies.py"], merged=MAR)

    found = freshness(SCOPE, [f"{REPO}#1"])[f"{REPO}#1"]

    assert (found.state, found.signals) == ("possibly_outdated", ["churn"])
    assert (found.files_changed, found.files_total) == (2, 2)
    assert [c.source for c in found.changed_by] == [f"{REPO}#3", f"{REPO}#2"]


def test_one_later_pr_is_not_enough_churn():
    """A single follow-up touching the same files is ordinary maintenance."""
    pr(1, AUTH, merged=JAN)
    pr(2, AUTH, merged=FEB)
    assert state(f"{REPO}#1") == "current"


def test_churn_below_the_file_share_is_not_enough():
    pr(1, ["a.py", "b.py", "c.py", "d.py"], merged=JAN)
    pr(2, ["a.py"], merged=FEB)
    pr(3, ["a.py"], merged=MAR)
    assert state(f"{REPO}#1") == "current"


def test_a_deleted_file_flags_it_on_its_own():
    pr(1, AUTH, merged=JAN)
    pr(2, {"src/auth/session.py": "removed"}, merged=FEB)

    found = freshness(SCOPE, [f"{REPO}#1"])[f"{REPO}#1"]

    assert found.signals == ["removed"]
    assert found.changed_by[0].removed == ["src/auth/session.py"]


def test_thresholds_are_settings(monkeypatch):
    monkeypatch.setattr(settings, "stale_min_later_changes", 1)
    pr(1, AUTH, merged=JAN)
    pr(2, AUTH, merged=FEB)
    assert state(f"{REPO}#1") == "possibly_outdated"


# ------------------------------------------------------- what must not flag

def test_changes_before_the_decision_do_not_count():
    pr(1, AUTH, merged=JAN)
    pr(2, AUTH, merged=FEB)
    pr(3, AUTH, merged=MAR)
    assert state(f"{REPO}#3") == "current"


def test_unmerged_prs_are_not_changes():
    pr(1, AUTH, merged=JAN)
    pr(2, AUTH, merged=None)
    pr(3, {"src/auth/session.py": "removed"}, merged=None)
    assert state(f"{REPO}#1") == "current"


def test_later_prs_that_mention_the_decision_do_not_count():
    """Their authors knew the decision and did not say it was replaced."""
    pr(1, AUTH, merged=JAN)
    pr(2, ["src/auth/session.py"], "Keeps the approach from #1.", merged=FEB)
    pr(3, {"src/auth/cookies.py": "removed"}, "Follow-up to #1.", merged=MAR)
    assert state(f"{REPO}#1") == "current"


def test_a_decision_that_mentions_the_later_one_is_also_linked():
    pr(2, ["src/auth/session.py"], merged=FEB)
    pr(1, AUTH, merged=JAN)
    pr(3, ["src/auth/cookies.py"], merged=MAR)
    # #1 linking forward to #2 is unusual but still says the two are known
    # to each other, so only #3 counts: not enough on its own.
    graph.index_decision(SCOPE, f"{REPO}#1", body="See #2.", repo=REPO)
    assert state(f"{REPO}#1") == "current"


def test_a_decision_without_recorded_files_is_not_judged():
    episodic.record_event(SCOPE, kind="pr", source=f"{REPO}#1", title="x", body="x",
                          repo=REPO, occurred_at=JAN)
    found = freshness(SCOPE, [f"{REPO}#1"])[f"{REPO}#1"]
    assert (found.state, found.files_total) == ("current", 0)


def test_scopes_are_isolated():
    pr(1, AUTH, merged=JAN)
    pr(2, ["src/auth/session.py"], merged=FEB, scope="gh:other")
    pr(3, ["src/auth/cookies.py"], merged=MAR, scope="gh:other")
    assert state(f"{REPO}#1") == "current"


# ---------------------------------------------------------- where it shows

def outdated_auth_decision() -> str:
    pr(1, AUTH, "Sessions over JWTs for revocation.", merged=JAN, title="Server sessions")
    pr(2, ["src/auth/session.py"], merged=FEB)
    pr(3, ["src/auth/cookies.py"], merged=MAR)
    return f"{REPO}#1"


def test_decision_reports_freshness_separately_from_status():
    source = outdated_auth_decision()
    found = graph.decision(SCOPE, source)

    assert found["status"] == "active", "an inference never changes the declared status"
    assert found["freshness"]["state"] == "possibly_outdated"
    assert found["freshness_note"] == (
        "possibly outdated: 2 of its 2 files changed since by acme/api#3, acme/api#2, "
        "none of which said it replaced it")


def test_overturned_decisions_have_no_freshness():
    pr(1, AUTH, merged=JAN)
    pr(2, AUTH, "Supersedes #1", merged=FEB)
    assert graph.decision(SCOPE, f"{REPO}#1")["freshness"] is None


def test_stale_list_is_active_decisions_only_deleted_files_first():
    churned = outdated_auth_decision()
    pr(10, ["src/billing/invoice.py"], merged=JAN)
    pr(11, {"src/billing/invoice.py": "removed"}, merged=FEB)
    pr(20, ["src/legacy.py"], merged=JAN)
    pr(21, ["src/legacy.py"], "Supersedes #20", merged=FEB)       # declared, not stale
    pr(22, ["src/legacy.py"], merged=MAR)

    found = [d["source"] for d in graph.stale_decisions(SCOPE)]

    assert found == [f"{REPO}#10", churned]


def test_pr_check_warns_about_possibly_outdated_decisions():
    outdated_auth_decision()
    result = decision_check.check(SCOPE, ["src/auth/session.py"], repo=REPO, number=99)
    text = decision_check.render(result)

    [entry] = [line for line in text.splitlines() if "acme/api#1**" in line]
    assert "⚠️ possibly outdated: 2 of its 2 files changed since" in entry


def test_pr_check_prefers_the_authors_own_declaration_over_the_warning():
    outdated_auth_decision()
    result = decision_check.check(SCOPE, ["src/auth/session.py"], body="Replaces #1",
                                  repo=REPO, number=99)
    entry = next(line for line in decision_check.render(result).splitlines()
                 if "acme/api#1**" in line)
    assert "this PR says it supersedes it" in entry
    assert "possibly outdated" not in entry


def test_agent_tool_hedges_rather_than_overrules():
    source = outdated_auth_decision()
    tool = {t.name: t for t in build_tools(SCOPE, "acme", Collector())}["decision_status"]

    text = tool.invoke({"source": source})

    assert "status: active" in text
    assert "possibly outdated" in text
    assert "not as replaced" in text


def test_agent_path_tool_marks_it():
    outdated_auth_decision()
    tool = {t.name: t for t in build_tools(SCOPE, "acme", Collector())}["decisions_for_path"]
    assert "(active, possibly outdated) Server sessions" in tool.invoke({"path": "src/auth/"})


def test_api_stale(client):
    outdated_auth_decision()
    response = client.get("/v1/graph/stale", params={"user_id": SCOPE})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["decisions"][0]["freshness"]["signals"] == ["churn"]


@pytest.mark.parametrize("limit", [0, 101])
def test_api_stale_validation(client, limit):
    response = client.get("/v1/graph/stale", params={"user_id": SCOPE, "limit": limit})
    assert response.status_code == 422
