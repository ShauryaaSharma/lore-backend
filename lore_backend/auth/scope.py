"""Decide which Canon scope a request may touch. Ported from the
prototype's `resolve_scope`: when auth is on, the scope comes from the
API key and the caller cannot override it (no cross-account reads). When
auth is off, falls back to the single-tenant default account."""

from __future__ import annotations

from lore_backend.auth.keys import AuthResult, auth_enabled, resolve
from lore_backend.config import settings
from lore_backend.retrieval.canon import account_scope


def resolve_scope(user_id: str, api_key: str) -> tuple[str | None, str | None, AuthResult | None]:
    """Returns (scope, error, auth_result). `error` is set when the request
    should be rejected (401)."""
    if auth_enabled():
        auth = resolve(api_key)
        if not auth:
            return None, "missing or invalid Lore API key", None
        return auth.scope, None, auth

    if user_id in ("", "demo") and settings.lore_default_account:
        return account_scope(settings.lore_default_account), None, None
    return user_id or "demo", None, None
