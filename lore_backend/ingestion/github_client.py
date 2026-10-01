"""GitHub App authentication + REST helpers.

    App JWT  (signed with the App's private key, RS256)
        -> Installation access token  (per-installation, short-lived)
                -> normal REST calls scoped to that installation's repos

Ported from the prototype's `github_app.py` with two additions: every network
call goes through `retry()` (exponential backoff + jitter on network errors
and 429/5xx) and a shared `CircuitBreaker` so a GitHub outage fails fast
instead of hanging every in-flight backfill job.

`app_configured()` returns False when the App isn't set up; callers skip the
App-powered paths (mirrors the original design — best-effort, not required
for mock/dev mode).
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from lore_backend.config import settings
from lore_backend.resilience.circuit_breaker import CircuitBreaker
from lore_backend.resilience.retry import retry

logger = logging.getLogger("lore.github")

API = "https://api.github.com"

_breaker = CircuitBreaker(
    failure_threshold=settings.circuit_breaker_failure_threshold,
    cooldown_seconds=settings.circuit_breaker_cooldown_seconds,
    name="github",
)


def _retryable_response(resp) -> bool:
    return getattr(resp, "status_code", None) in (429, 500, 502, 503, 504)


def _request(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", settings.http_timeout_seconds)

    @retry(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay_seconds,
        retry_on=(requests.RequestException,),
        should_retry_response=_retryable_response,
    )
    def _do():
        return requests.request(method, url, **kwargs)

    return _breaker.call(_do)


def _load_private_key() -> str:
    raw = settings.github_app_private_key.strip()
    if raw:
        if "BEGIN" not in raw:
            try:
                raw = base64.b64decode(raw).decode()
            except Exception:
                pass
        return raw.replace("\\n", "\n")
    path = settings.github_app_private_key_path.strip()
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
    return ""


def app_configured() -> bool:
    return bool(settings.github_app_id) and bool(_load_private_key())


def _app_jwt() -> str:
    import jwt  # PyJWT, imported lazily so mock mode needs no crypto deps

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, _load_private_key(), algorithm="RS256")


# Installation tokens are valid ~1h; cache them so a backfill doesn't remint
# on every repo. Keyed by installation id -> (token, expiry_epoch).
_token_cache: dict[int, tuple[str, float]] = {}


def installation_token(installation_id: int) -> Optional[str]:
    if not app_configured():
        return None
    cached = _token_cache.get(installation_id)
    if cached and cached[1] - 120 > time.time():
        return cached[0]

    resp = _request(
        "POST",
        f"{API}/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {_app_jwt()}",
            "Accept": "application/vnd.github+json",
        },
    )
    if resp.status_code not in (200, 201):
        logger.warning("installation_token failed: %s %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json()
    token = data.get("token", "")
    exp = time.time() + 55 * 60
    if data.get("expires_at"):
        try:
            exp = datetime.fromisoformat(
                data["expires_at"].replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            pass
    _token_cache[installation_id] = (token, exp)
    return token


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def list_app_installations() -> list[dict]:
    if not app_configured():
        return []
    out, page = [], 1
    while True:
        resp = _request(
            "GET",
            f"{API}/app/installations?per_page=100&page={page}",
            headers={
                "Authorization": f"Bearer {_app_jwt()}",
                "Accept": "application/vnd.github+json",
            },
        )
        if resp.status_code != 200:
            break
        batch = resp.json()
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return out


def list_installation_repos(token: str, limit: int = 100) -> list[dict]:
    repos, page = [], 1
    while True:
        resp = _request(
            "GET",
            f"{API}/installation/repositories?per_page=100&page={page}",
            headers=_headers(token),
        )
        if resp.status_code != 200:
            break
        batch = resp.json().get("repositories", [])
        repos.extend(batch)
        if len(batch) < 100 or len(repos) >= limit:
            break
        page += 1
    return repos[:limit]


def list_recent_prs(token: str, owner: str, repo: str, since: datetime,
                    max_prs: int = 100) -> list[dict]:
    out, page = [], 1
    while len(out) < max_prs:
        resp = _request(
            "GET",
            f"{API}/repos/{owner}/{repo}/pulls"
            f"?state=all&sort=updated&direction=desc&per_page=50&page={page}",
            headers=_headers(token),
        )
        if resp.status_code != 200:
            break
        batch = resp.json()
        if not batch:
            break
        stop = False
        for pr in batch:
            updated = _parse_dt(pr.get("updated_at"))
            if updated and updated < since:
                stop = True
                break
            out.append(pr)
        if stop or len(batch) < 50:
            break
        page += 1
    return out[:max_prs]


def fetch_pr_threads(token: str, owner: str, repo: str, number: int,
                     max_comments: int = 40) -> str:
    lines: list[str] = []
    for kind, path in (
        ("comment", f"issues/{number}/comments"),
        ("review", f"pulls/{number}/comments"),
    ):
        resp = _request(
            "GET",
            f"{API}/repos/{owner}/{repo}/{path}?per_page={max_comments}",
            headers=_headers(token),
        )
        if resp.status_code != 200:
            continue
        for c in resp.json():
            author = (c.get("user") or {}).get("login", "?")
            body = (c.get("body") or "").strip()
            if body:
                lines.append(f"[{kind}] @{author}: {body}")
    return "\n".join(lines)


def list_open_prs(token: str, owner: str, repo: str, limit: int = 50) -> list[dict]:
    resp = _request(
        "GET", f"{API}/repos/{owner}/{repo}/pulls?state=open&per_page={limit}",
        headers=_headers(token),
    )
    return resp.json() if resp.status_code == 200 else []


def fetch_pr(token: str, owner: str, repo: str, number: int) -> Optional[dict]:
    """One PR by number — the agent's escape hatch when the Canon has no
    decision for something the question names explicitly."""
    resp = _request("GET", f"{API}/repos/{owner}/{repo}/pulls/{number}",
                    headers=_headers(token))
    return resp.json() if resp.status_code == 200 else None


def fetch_pr_files(token: str, owner: str, repo: str, number: int,
                   max_files: int = 20) -> list[dict]:
    """Changed files, not the raw patch. What was touched is the part that
    explains a decision; the diff hunks are mostly tokens the model has to
    read past."""
    resp = _request(
        "GET", f"{API}/repos/{owner}/{repo}/pulls/{number}/files?per_page={max_files}",
        headers=_headers(token),
    )
    if resp.status_code != 200:
        return []
    return [
        {"filename": f.get("filename", ""), "status": f.get("status", ""),
         "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)}
        for f in resp.json()
    ]


def search_commits(token: str, query: str, repo: str = "", limit: int = 10) -> list[dict]:
    """Commit-message search. Catches decisions recorded as a `Why:` trailer
    by the CLI but never surfaced in a PR discussion."""
    q = f"{query} repo:{repo}" if repo else query
    resp = _request(
        "GET", f"{API}/search/commits?q={requests.utils.quote(q)}&per_page={limit}",
        headers={**_headers(token), "Accept": "application/vnd.github.cloak-preview+json"},
    )
    if resp.status_code != 200:
        return []
    out = []
    for item in resp.json().get("items", []):
        commit = item.get("commit", {}) or {}
        out.append({
            "sha": (item.get("sha") or "")[:7],
            "message": (commit.get("message") or "").strip(),
            "author": ((commit.get("author") or {}).get("name") or ""),
            "date": ((commit.get("author") or {}).get("date") or "")[:10],
            "repo": ((item.get("repository") or {}).get("full_name") or ""),
            "url": item.get("html_url", ""),
        })
    return out


def post_issue_comment(token: str, owner: str, repo: str, number: int,
                       body: str) -> bool:
    resp = _request(
        "POST", f"{API}/repos/{owner}/{repo}/issues/{number}/comments",
        headers=_headers(token), json={"body": body},
    )
    return resp.status_code in (200, 201)


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
