"""`@lore` mentions in PR and issue threads: who can trigger an answer, what
counts as a question, and the reply that comes back."""

from __future__ import annotations

import json

import pytest

from lore_backend.config import settings
from lore_backend.ingestion import github_client as gh
from lore_backend.ingestion import mentions
from lore_backend.retrieval import canon
from lore_backend.storage.db import get_conn

REPO = "acme/api"


# ----------------------------------------------------------------- parsing

@pytest.mark.parametrize("body, question", [
    ("@lore why do we use JWTs here?", "why do we use JWTs here?"),
    ("@Lore: why JWTs?", "why JWTs?"),
    ("Good catch. @lore why was this a session store?", "why was this a session store?"),
    ("@lore why JWTs?\n\nUnrelated second paragraph.", "why JWTs?"),
    ("@lore why do we\nuse JWTs?", "why do we use JWTs?"),
])
def test_questions(body, question):
    assert mentions.parse_mention(body) == question


@pytest.mark.parametrize("body", [
    "Thanks!",
    "@lore",
    "> @lore why JWTs?\n\nI had the same question.",
    "```\n@lore why JWTs?\n```",
    "mail me at dev@lore.dev",
    "@lorebot why JWTs?",
    "@lore-app why JWTs?",
    "https://example.com/@lore why",
])
def test_not_questions(body):
    assert mentions.parse_mention(body) is None


def test_long_questions_are_truncated():
    assert len(mentions.parse_mention("@lore " + "why " * 500)) == mentions.MAX_QUESTION_CHARS


def test_trigger_is_configurable():
    assert mentions.parse_mention("@decisions why JWTs?", trigger="@decisions") == "why JWTs?"
    assert mentions.parse_mention("@lore why JWTs?", trigger="@decisions") is None


# ----------------------------------------------------------------- webhook

@pytest.fixture
def github(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(gh, "app_configured", lambda: True)
    monkeypatch.setattr(gh, "installation_token", lambda installation_id: "token")
    state = {"reactions": [], "posted": []}
    monkeypatch.setattr(gh, "add_reaction",
                        lambda token, owner, repo, comment_id, content:
                        state["reactions"].append((repo, comment_id, content)) or True)
    monkeypatch.setattr(gh, "post_issue_comment",
                        lambda token, owner, repo, number, body:
                        state["posted"].append((repo, number, body)) or True)
    return state


def comment_event(body: str = "@lore why JWTs?", *, action: str = "created",
                  association: str = "MEMBER", login: str = "dev", user_type: str = "User",
                  is_pr: bool = True) -> dict:
    issue = {"number": 5, "title": "Rework auth"}
    if is_pr:
        issue["pull_request"] = {"url": "..."}
    return {
        "action": action, "installation": {"id": 1}, "repository": {"full_name": REPO},
        "issue": issue,
        "comment": {"id": 99, "body": body, "author_association": association,
                    "html_url": "https://github.com/acme/api/pull/5#c99",
                    "user": {"login": login, "type": user_type}},
    }


def queued_jobs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("select type, payload from jobs order by id").fetchall()
    return [{"type": r[0], **r[1]} for r in rows]


def test_a_question_is_acknowledged_and_queued(github):
    result = mentions.handle_issue_comment_event(comment_event())

    assert result["question"] == "why JWTs?"
    assert github["reactions"] == [("api", 99, "eyes")]
    [job] = queued_jobs()
    assert job["type"] == mentions.JOB_TYPE
    assert (job["repo"], job["number"], job["is_pr"], job["asker"]) == (REPO, 5, True, "dev")


def test_issues_are_answered_too(github):
    mentions.handle_issue_comment_event(comment_event(is_pr=False))
    assert queued_jobs()[0]["is_pr"] is False


@pytest.mark.parametrize("event, reason", [
    (comment_event(action="edited"), "action=edited"),
    (comment_event("Looks good"), "no mention"),
    (comment_event(user_type="Bot"), "bot comment"),
    (comment_event(login="lore-app[bot]"), "bot comment"),
    (comment_event(association="NONE"), "author_association=NONE not allowed"),
    (comment_event(association="CONTRIBUTOR"), "author_association=CONTRIBUTOR not allowed"),
])
def test_ignored(github, event, reason):
    assert mentions.handle_issue_comment_event(event)["ignored"] == reason
    assert queued_jobs() == []
    assert github["reactions"] == []


def test_allowed_associations_are_configurable(github, monkeypatch):
    monkeypatch.setattr(settings, "mention_allowed_associations", "owner, contributor")
    assert "queued" in mentions.handle_issue_comment_event(comment_event(association="CONTRIBUTOR"))


def test_mock_mode_does_not_answer(github, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    assert mentions.handle_issue_comment_event(comment_event())["mode"] == "mock"
    assert queued_jobs() == []


def test_without_app_auth_nothing_is_queued(github, monkeypatch):
    monkeypatch.setattr(gh, "app_configured", lambda: False)
    assert mentions.handle_issue_comment_event(comment_event())["answered"] is False
    assert queued_jobs() == []


def test_webhook_route_dispatches_issue_comments(client, github):
    response = client.post("/webhook/github", content=json.dumps(comment_event()),
                           headers={"X-GitHub-Event": "issue_comment",
                                    "X-GitHub-Delivery": "mention-1"})
    assert response.status_code == 200
    assert response.json()["question"] == "why JWTs?"


# ------------------------------------------------------------------ worker

def job(**overrides) -> dict:
    payload = {"installation_id": 1, "repo": REPO, "number": 5, "title": "Rework auth",
               "is_pr": True, "question": "why JWTs?", "asker": "dev", "comment_url": ""}
    payload.update(overrides)
    return {"id": 1, "payload": payload}


@pytest.fixture
def answer(monkeypatch):
    asked = []

    def fake_answer_why(question, scope):
        asked.append((question, scope))
        return {"answer": "A Redis failover logged everyone out [acme/api#482].",
                "sources": [["PR", "acme/api#482", "https://github.com/acme/api/pull/482"]]}

    monkeypatch.setattr(canon, "answer_why", fake_answer_why)
    return asked


def test_worker_answers_in_the_thread(github, answer):
    mentions.handle_answer_mention(job())

    assert answer == [("why JWTs?\n\nAsked on PR acme/api#5 (Rework auth).", "gh:acme")]
    [(repo, number, body)] = github["posted"]
    assert (repo, number) == ("api", 5)
    assert body.startswith("> why JWTs?\n\n@dev A Redis failover")
    assert "- [acme/api#482](https://github.com/acme/api/pull/482)" in body


def test_worker_retries_when_github_rejects_the_reply(github, answer, monkeypatch):
    monkeypatch.setattr(gh, "post_issue_comment", lambda *a: False)
    with pytest.raises(RuntimeError, match="rejected"):
        mentions.handle_answer_mention(job())


def test_worker_retries_without_a_token(github, answer, monkeypatch):
    monkeypatch.setattr(gh, "installation_token", lambda installation_id: None)
    with pytest.raises(RuntimeError, match="token"):
        mentions.handle_answer_mention(job())


def test_worker_is_registered_with_the_queue():
    from lore_backend.jobs.handlers import HANDLERS
    assert HANDLERS[mentions.JOB_TYPE] is mentions.handle_answer_mention


# ----------------------------------------------------------------- reply

def test_reply_without_sources_has_no_sources_section():
    body = mentions.render_reply("why X?", "dev", {"answer": "No record of X.", "sources": []})
    assert "**Sources**" not in body
    assert body.startswith("> why X?\n\n@dev No record of X.")


def test_reply_source_without_a_url_is_plain_text():
    body = mentions.render_reply("why X?", "dev", {"answer": "a", "sources": [["memory", "ADR-7"]]})
    assert "- ADR-7" in body
