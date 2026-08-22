"""Shared FastAPI dependencies: extracting the caller's API key, resolving
their Canon scope, and per-key rate limiting. Thin — the actual logic lives
in `lore_backend.auth`."""

from __future__ import annotations

from fastapi import Header, HTTPException

from lore_backend.auth.ratelimit import limiter
from lore_backend.auth.scope import resolve_scope


def api_key_from_headers(authorization: str = Header(None), x_lore_key: str = Header(None),
                         key: str = "") -> str:
    if x_lore_key:
        return x_lore_key.strip()
    if key:
        return key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def require_scope(user_id: str = "demo", authorization: str = Header(None),
                  x_lore_key: str = Header(None), key: str = "") -> str:
    api_key = api_key_from_headers(authorization, x_lore_key, key)
    scope, err, auth = resolve_scope(user_id, api_key)
    if err:
        raise HTTPException(status_code=401, detail=err)
    _enforce_rate_limit(api_key or scope)
    return scope


def require_account(account: str, authorization: str = Header(None),
                    x_lore_key: str = Header(None), key: str = "") -> str:
    """For admin actions bound to a GitHub account (backfill). When auth is
    on, the key's account must match `account` and must carry admin scope."""
    from lore_backend.auth.keys import auth_enabled, resolve

    api_key = api_key_from_headers(authorization, x_lore_key, key)
    _enforce_rate_limit(api_key or account or "anon")
    if not auth_enabled():
        return account

    auth = resolve(api_key)
    if not auth:
        raise HTTPException(status_code=401, detail="missing or invalid Lore API key")
    if not auth.has_scope("admin:backfill"):
        raise HTTPException(status_code=403, detail="key lacks admin:backfill scope")
    login = auth.scope[3:] if auth.scope.startswith("gh:") else auth.scope
    if account and account.lower() != login.lower():
        raise HTTPException(status_code=403, detail="key not authorized for this account")
    return account or login


def _enforce_rate_limit(bucket_key: str) -> None:
    if not limiter.allow(bucket_key):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
