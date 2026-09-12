"""Job handlers — what actually runs when the worker claims a job. This is
where the prototype's `backfill_installation` logic lives now, rewritten to
report progress into the `jobs` row (via `queue.update_progress`) instead of
a single global in-process dict."""

from __future__ import annotations

import logging

from app.config import settings
from app.ingestion import github_client as gh
from app.jobs import queue
from app.retrieval import canon
from app.retrieval.summarize import welcome_body

logger = logging.getLogger("lore.jobs")


def handle_backfill_installation(job: dict) -> None:
    payload = job["payload"]
    installation_id = payload["installation_id"]
    account = payload["account"]
    repos = payload["repos"]  # list of {"full_name": ...}
    post_welcome = payload.get("post_welcome", True)

    scope = canon.account_scope(account)
    since = gh.days_ago(settings.backfill_days)
    repo_names = [r["full_name"] for r in repos]

    progress = {
        "state": "running", "account": scope, "repos_total": len(repos),
        "repos_done": 0, "prs_captured": 0, "comments_posted": 0,
        "current_repo": None,
    }
    queue.update_progress(job["id"], progress)

    if settings.mode != "live":
        progress.update(state="error")
        queue.update_progress(job["id"], progress)
        raise RuntimeError("live mode required (set GROQ_API_KEY)")

    token = gh.installation_token(installation_id)
    if not token:
        progress.update(state="error")
        queue.update_progress(job["id"], progress)
        raise RuntimeError(
            "could not mint installation token (check GITHUB_APP_ID / private key)"
        )

    captured = comments = 0
    for r in repos:
        full = r["full_name"]
        owner, _, name = full.partition("/")
        progress["current_repo"] = full
        queue.update_progress(job["id"], progress)

        for pr in gh.list_recent_prs(token, owner, name, since):
            threads = gh.fetch_pr_threads(token, owner, name, pr["number"])
            canon.inscribe_pr(
                scope, number=pr["number"], title=pr.get("title") or "",
                body=(pr.get("body") or ""), threads=threads,
                author=(pr.get("user") or {}).get("login", ""),
                repo_full=full, url=pr.get("html_url", ""),
                merged_at=pr.get("merged_at") or "",
            )
            captured += 1
            progress["prs_captured"] = captured
            queue.update_progress(job["id"], progress)

        if post_welcome:
            body = welcome_body(account, repo_names, settings.backfill_days)
            for pr in gh.list_open_prs(token, owner, name):
                if gh.post_issue_comment(token, owner, name, pr["number"], body):
                    comments += 1
                    progress["comments_posted"] = comments
                    queue.update_progress(job["id"], progress)

        progress["repos_done"] += 1
        queue.update_progress(job["id"], progress)

    progress.update(state="done", current_repo=None)
    queue.update_progress(job["id"], progress)


HANDLERS = {
    "backfill_installation": handle_backfill_installation,
}
