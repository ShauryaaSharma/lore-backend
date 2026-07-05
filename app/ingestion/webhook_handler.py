"""GitHub webhook entrypoints. Ported from the prototype's
`handle_pull_request_event` / `handle_installation_event`, with one
structural change: install-time backfill is now `queue.enqueue(...)`
instead of `threading.Thread(...).start()`, so it survives a worker
restart and multiple installs never share mutable state."""

from __future__ import annotations

import hashlib
import hmac

from app.config import settings
from app.ingestion import github_client as gh
from app.jobs import queue
from app.retrieval import canon
from app.retrieval.summarize import pr_understanding_comment
from app.storage.queries import get_or_create_tenant_for_account, upsert_installation


def verify_github_signature(raw: bytes, signature_header: str) -> bool:
    """Confirm a webhook really came from GitHub: HMAC-SHA256 over the raw
    body, keyed by the webhook secret. If no secret is configured (local
    dev), skip."""
    if not settings.github_webhook_secret:
        return True
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def handle_pull_request_event(payload: dict) -> dict:
    """React to pull-request webhooks:
      - opened / reopened / ready_for_review -> comment with Lore's read of it.
      - closed & merged -> inscribe the PR (a merge = a finalized decision).
    """
    action = payload.get("action")
    pr = payload.get("pull_request") or {}
    repo_full = (payload.get("repository") or {}).get("full_name", "")
    owner = repo_full.split("/")[0] if "/" in repo_full else ""
    repo_name = repo_full.split("/")[1] if "/" in repo_full else repo_full
    number = pr.get("number")
    title = pr.get("title", "")
    body = (pr.get("body") or "").strip()
    author = (pr.get("user") or {}).get("login", "")
    url = pr.get("html_url", "")
    install_id = (payload.get("installation") or {}).get("id")
    scope = canon.account_scope(owner)

    if action in ("opened", "reopened", "ready_for_review"):
        if settings.mode == "mock":
            return {"ok": True, "commented": False, "mode": "mock", "pr": number}
        if not (install_id and gh.app_configured()):
            return {"ok": True, "commented": False,
                    "reason": "App auth not configured — cannot post comment"}
        token = gh.installation_token(install_id)
        if not token:
            return {"ok": True, "commented": False, "reason": "no installation token"}
        threads = gh.fetch_pr_threads(token, owner, repo_name, number)
        comment = pr_understanding_comment(title, body, threads)
        posted = gh.post_issue_comment(token, owner, repo_name, number, comment)
        return {"ok": True, "commented": posted, "pr": number, "action": action}

    if action != "closed" or not pr.get("merged", False):
        return {"ok": True, "captured": False,
                "reason": f"action={action}, merged={pr.get('merged')}"}

    if settings.mode == "mock":
        return {"ok": True, "captured": False, "mode": "mock",
                "pr": number, "note": "set GROQ_API_KEY to capture"}

    threads = ""
    if install_id and gh.app_configured():
        token = gh.installation_token(install_id)
        if token:
            threads = gh.fetch_pr_threads(token, owner, repo_name, number)

    canon.inscribe_pr(
        scope, number=number, title=title, body=body, threads=threads,
        author=author, repo_full=repo_full, url=url,
        merged_at=pr.get("merged_at") or "",
    )
    return {"ok": True, "captured": True, "pr": number, "repo": repo_full, "scope": scope}


def handle_installation_event(payload: dict) -> dict:
    """Webhook entrypoint for `installation` / `installation_repositories`.

    Enqueues a `backfill_installation` job instead of running inline — the
    webhook responds immediately (GitHub times out at ~10s) and the worker
    picks the job up, independent of any other install running concurrently."""
    action = payload.get("action")
    if action not in ("created", "added", "new_permissions_accepted", "unsuspend"):
        return {"ok": True, "ignored": f"installation action={action}"}

    inst = payload.get("installation") or {}
    installation_id = inst.get("id")
    account = (inst.get("account") or {}).get("login", "")
    account_type = (inst.get("account") or {}).get("type", "User").lower()
    account_type = "org" if account_type == "organization" else "user"

    repos = payload.get("repositories") or payload.get("repositories_added") or []

    if not gh.app_configured():
        return {"ok": True, "captured": False,
                "note": "GitHub App auth not configured — set GITHUB_APP_ID and "
                        "GITHUB_APP_PRIVATE_KEY to enable backfill"}
    if not installation_id:
        return {"ok": True, "captured": False, "note": "no installation id"}

    if not repos:
        token = gh.installation_token(installation_id)
        if token:
            repos = gh.list_installation_repos(token)

    if not repos:
        return {"ok": True, "captured": False, "account": account,
                "note": "no repositories to index"}

    tenant_id = get_or_create_tenant_for_account(account)
    upsert_installation(tenant_id, installation_id, account, account_type)

    repo_payload = [{"full_name": r.get("full_name") or f"{account}/{r.get('name', '')}"}
                    for r in repos]
    job_id = queue.enqueue(
        "backfill_installation",
        {
            "installation_id": installation_id,
            "account": account,
            "repos": repo_payload,
            "post_welcome": True,
        },
        tenant_id=tenant_id,
    )

    return {"ok": True, "backfill": "queued", "job_id": job_id, "account": account,
            "repos": len(repo_payload), "days": settings.backfill_days}


def trigger_backfill(account: str = "") -> dict:
    """Manually start a backfill without waiting for a webhook — looks up the
    App's installations (as the App itself), optionally filters to
    `account`, and enqueues the job."""
    if not gh.app_configured():
        return {"ok": False, "error": "GitHub App auth not configured "
                "(set GITHUB_APP_ID + GITHUB_APP_PRIVATE_KEY)"}
    if settings.mode != "live":
        return {"ok": False, "error": "live mode required (set GROQ_API_KEY)"}

    installs = gh.list_app_installations()
    if not installs:
        return {"ok": False, "error": "App has no installations, or the App "
                "JWT was rejected (check GITHUB_APP_ID / private key)"}

    if account:
        want = account.strip().lower()
        installs = [i for i in installs
                    if (i.get("account") or {}).get("login", "").lower() == want]
        if not installs:
            return {"ok": False, "error": f"App is not installed on '{account}'. "
                    "Install it there first."}

    inst = installs[0]
    installation_id = inst.get("id")
    login = (inst.get("account") or {}).get("login", "")
    account_type = (inst.get("account") or {}).get("type", "User").lower()
    account_type = "org" if account_type == "organization" else "user"

    token = gh.installation_token(installation_id)
    repos = gh.list_installation_repos(token) if token else []
    if not repos:
        return {"ok": False, "account": login,
                "error": "no repositories visible to this installation"}

    tenant_id = get_or_create_tenant_for_account(login)
    upsert_installation(tenant_id, installation_id, login, account_type)

    repo_payload = [{"full_name": r.get("full_name") or f"{login}/{r.get('name', '')}"}
                    for r in repos]
    job_id = queue.enqueue(
        "backfill_installation",
        {
            "installation_id": installation_id,
            "account": login,
            "repos": repo_payload,
            "post_welcome": True,
        },
        tenant_id=tenant_id,
    )
    return {"ok": True, "backfill": "queued", "job_id": job_id, "account": login,
            "repos": len(repo_payload), "days": settings.backfill_days}
