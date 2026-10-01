"""`@lore why ...?` in a PR or issue thread, answered in that thread.

The CLI and the editor extension need someone to leave the review to ask.
The question usually comes up *in* the review -- "why is this a JWT and not
a session?" -- so that is where it should be answerable, and where the
answer stays for the next reader.

Two halves, because GitHub gives a webhook about ten seconds and the agent
can take longer:

  webhook  (handle_issue_comment_event)  filter, react with 👀, enqueue
  worker   (handle_answer_mention)       answer through /why, reply

The answer goes through canon.answer_why, so it is the same agent, the same
tenant scope and the same citation guardrail as every other surface: an
answer it cannot source is withheld here too.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from lore_backend.config import settings
from lore_backend.ingestion import github_client as gh
from lore_backend.jobs import queue

logger = logging.getLogger("lore.mentions")

JOB_TYPE = "answer_mention"
MAX_QUESTION_CHARS = 1000

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def parse_mention(body: str, trigger: str = "") -> Optional[str]:
    """The question addressed to Lore in a comment, or None.

    Fenced code and quoted lines are skipped: a reply that quotes an earlier
    "@lore why ...?" is not asking it again. The question is everything
    after the trigger up to the end of its paragraph.
    """
    trigger = trigger or settings.mention_trigger
    text = _FENCE_RE.sub("", body or "")
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))
    m = re.search(rf"(?<![\w/@]){re.escape(trigger)}(?![\w-])[\s:,]*(?P<q>.*?)(?:\n\s*\n|\Z)",
                  text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    question = " ".join(m.group("q").split())
    return question[:MAX_QUESTION_CHARS] or None


def handle_issue_comment_event(payload: dict) -> dict:
    """Webhook half: decide whether this comment is a question for Lore and,
    if so, queue it. Returns quickly whatever happens."""
    if payload.get("action") != "created":
        return {"ok": True, "ignored": f"action={payload.get('action')}"}

    comment = payload.get("comment") or {}
    user = comment.get("user") or {}
    login = user.get("login", "")
    # Lore's own replies quote the question; never answer a bot, including
    # ourselves, or one reply becomes an infinite thread.
    if user.get("type") == "Bot" or login.endswith("[bot]"):
        return {"ok": True, "ignored": "bot comment"}

    question = parse_mention(comment.get("body") or "")
    if not question:
        return {"ok": True, "ignored": "no mention"}

    allowed = {a.strip().upper() for a in settings.mention_allowed_associations.split(",")
               if a.strip()}
    association = (comment.get("author_association") or "NONE").upper()
    if association not in allowed:
        return {"ok": True, "ignored": f"author_association={association} not allowed"}

    if settings.mode == "mock":
        return {"ok": True, "answered": False, "mode": "mock",
                "note": "set GROQ_API_KEY to answer mentions"}

    install_id = (payload.get("installation") or {}).get("id")
    if not (install_id and gh.app_configured()):
        return {"ok": True, "answered": False,
                "reason": "App auth not configured — cannot reply"}

    repo_full = (payload.get("repository") or {}).get("full_name", "")
    issue = payload.get("issue") or {}
    owner, _, name = repo_full.partition("/")

    token = gh.installation_token(install_id)
    if token and comment.get("id"):
        gh.add_reaction(token, owner, name, comment["id"], "eyes")

    job_id = queue.enqueue(JOB_TYPE, {
        "installation_id": install_id,
        "repo": repo_full,
        "number": issue.get("number"),
        "title": issue.get("title", ""),
        "is_pr": "pull_request" in issue,
        "question": question,
        "asker": login,
        "comment_url": comment.get("html_url", ""),
    })
    return {"ok": True, "queued": job_id, "question": question}


def handle_answer_mention(job: dict) -> None:
    """Worker half: answer and reply. Raises if the reply cannot be posted,
    so the queue retries; the answer is only produced again, never posted
    twice, because posting is the last step."""
    from lore_backend.retrieval import canon

    p = job["payload"]
    owner, _, name = p["repo"].partition("/")
    scope = canon.account_scope(owner)

    # Where it was asked, so "why does this PR ..." has a referent and the
    # agent knows which PR to fetch if the Canon has nothing on it.
    where = f"{'PR' if p.get('is_pr') else 'issue'} {p['repo']}#{p['number']}"
    if p.get("title"):
        where += f" ({p['title']})"
    result = canon.answer_why(f"{p['question']}\n\nAsked on {where}.", scope)

    token = gh.installation_token(p["installation_id"])
    if not token:
        raise RuntimeError("could not mint installation token")
    body = render_reply(p["question"], p["asker"], result)
    if not gh.post_issue_comment(token, owner, name, p["number"], body):
        raise RuntimeError(f"GitHub rejected the reply on {p['repo']}#{p['number']}")


def render_reply(question: str, asker: str, result: dict) -> str:
    """The reply comment: the question quoted (so the thread reads on its
    own), the answer, and its sources as links."""
    lines = [f"> {question}", "", f"@{asker} {result.get('answer', '').strip()}"]

    sources = result.get("sources") or []
    if sources:
        lines += ["", "**Sources**"]
        for entry in sources:
            label = entry[1] if len(entry) > 1 else str(entry)
            url = entry[2] if len(entry) > 2 else ""
            lines.append(f"- [{label}]({url})" if url else f"- {label}")

    lines += ["", "<sub>Answered from this team's recorded decisions. An answer Lore "
                  "cannot cite is withheld rather than guessed.</sub>"]
    return "\n".join(lines)
