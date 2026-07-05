"""API key management. Keys are hashed (sha256) before storage — never
logged or stored raw — so a DB leak doesn't leak usable credentials. Rotation
and revocation are DB writes, not a redeploy (the prototype's env-var keys
required re-uploading files to rotate).

Kept alongside an env-var fallback (`LORE_API_KEYS=key:login,...`) so a
solo self-hoster can run in mock/dev mode without touching Postgres at all.
DB-backed keys are the production path; the env fallback is checked first
since it's zero-cost and typically empty in production.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from app.config import settings
from app.storage.queries import (
    count_active_api_keys,
    create_tenant,
    insert_api_key,
    lookup_api_key,
    revoke_api_key,
    touch_api_key,
)


def _hash(key: str) -> str:
    return hashlib.sha256(key.strip().encode()).hexdigest()


def _parse_env_keys(raw: str) -> dict[str, str]:
    out = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        key, login = pair.split(":", 1)
        key, login = key.strip(), login.strip()
        if key and login:
            out[key] = login
    return out


_ENV_KEYS = _parse_env_keys(settings.lore_api_keys)


def auth_enabled() -> bool:
    """True once any key (env-configured or DB-issued) exists — every read
    endpoint then requires a valid key and answers only that key's scope."""
    return bool(_ENV_KEYS) or count_active_api_keys() > 0


class AuthResult:
    def __init__(self, scope: str, tenant_id: Optional[str], scopes: list[str],
                key_id: Optional[str] = None):
        self.scope = scope
        self.tenant_id = tenant_id
        self.scopes = scopes
        self.key_id = key_id

    def has_scope(self, required: str) -> bool:
        return required in self.scopes or "admin" in self.scopes


def resolve(api_key: str) -> Optional[AuthResult]:
    """Resolve a caller's API key to (scope, tenant_id, scopes). Checks the
    env-var map first (fast path, no DB round trip), then DB-backed keys."""
    api_key = (api_key or "").strip()
    if not api_key:
        return None

    login = _ENV_KEYS.get(api_key)
    if login:
        from app.retrieval.canon import account_scope
        return AuthResult(scope=account_scope(login), tenant_id=None,
                          scopes=["read:why", "admin:backfill"])

    row = lookup_api_key(_hash(api_key))
    if not row or row["revoked_at"] is not None:
        return None
    touch_api_key(row["id"])
    from app.retrieval.canon import account_scope
    return AuthResult(scope=account_scope(row["tenant_name"]), tenant_id=row["tenant_id"],
                      scopes=row["scopes"], key_id=row["id"])


def create_key(tenant_name: str, scopes: list[str]) -> tuple[str, str]:
    """Create a tenant (if needed) + a fresh API key. Returns (raw_key,
    tenant_id) — the raw key is shown to the caller exactly once."""
    tenant_id = create_tenant(tenant_name)
    raw_key = f"lk_{secrets.token_urlsafe(32)}"
    insert_api_key(tenant_id, _hash(raw_key), scopes)
    return raw_key, tenant_id


def revoke(key_id: str) -> None:
    revoke_api_key(key_id)
