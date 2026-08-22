"""Hand-written data-access functions for the control-plane tables. Kept thin
and explicit on purpose — no ORM, no query builder, this is the whole
vocabulary the rest of the app needs against Postgres."""

from __future__ import annotations

import json
from typing import Optional

from lore_backend.storage.db import get_conn

# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------
def create_tenant(name: str, plan: str = "free") -> str:
    with get_conn() as conn:
        row = conn.execute(
            "insert into tenants (name, plan) values (%s, %s) returning id",
            (name, plan),
        ).fetchone()
        conn.commit()
        return str(row[0])


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def insert_api_key(tenant_id: str, hashed_key: str, scopes: list[str]) -> str:
    with get_conn() as conn:
        row = conn.execute(
            """
            insert into api_keys (tenant_id, hashed_key, scopes)
            values (%s, %s, %s) returning id
            """,
            (tenant_id, hashed_key, scopes),
        ).fetchone()
        conn.commit()
        return str(row[0])


def lookup_api_key(hashed_key: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            """
            select ak.id, ak.tenant_id, ak.scopes, ak.revoked_at, t.name
            from api_keys ak join tenants t on t.id = ak.tenant_id
            where ak.hashed_key = %s
            """,
            (hashed_key,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "tenant_id": str(row[1]),
            "scopes": row[2],
            "revoked_at": row[3],
            "tenant_name": row[4],
        }


def touch_api_key(key_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "update api_keys set last_used_at = now() where id = %s", (key_id,)
        )
        conn.commit()


def revoke_api_key(key_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "update api_keys set revoked_at = now() where id = %s", (key_id,)
        )
        conn.commit()


def count_active_api_keys() -> int:
    with get_conn() as conn:
        row = conn.execute(
            "select count(*) from api_keys where revoked_at is null"
        ).fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# Installations / repos
# ---------------------------------------------------------------------------
def upsert_installation(tenant_id: str, github_installation_id: int,
                        account_login: str, account_type: str) -> str:
    with get_conn() as conn:
        row = conn.execute(
            """
            insert into installations (tenant_id, github_installation_id, account_login, account_type)
            values (%s, %s, %s, %s)
            on conflict (github_installation_id)
            do update set account_login = excluded.account_login
            returning id
            """,
            (tenant_id, github_installation_id, account_login, account_type),
        ).fetchone()
        conn.commit()
        return str(row[0])


def get_installation_id_for_account(account_login: str) -> Optional[int]:
    """The GitHub installation backing an account, so the agent's tools can
    mint a token for it. Returns None when the App isn't installed — the
    tools then say so rather than failing the whole run."""
    if not account_login:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "select github_installation_id from installations "
            "where lower(account_login) = lower(%s) order by id desc limit 1",
            (account_login,),
        ).fetchone()
    return int(row[0]) if row else None


def get_or_create_tenant_for_account(account_login: str) -> str:
    """One tenant per GitHub account for now — a tenant maps 1:1 to the
    account that installed the App. Kept separate from `installations` so a
    tenant can later span multiple installs (e.g. an org + its bot user)."""
    with get_conn() as conn:
        row = conn.execute(
            "select id from tenants where name = %s", (account_login,)
        ).fetchone()
        if row:
            return str(row[0])
        row = conn.execute(
            "insert into tenants (name) values (%s) returning id", (account_login,)
        ).fetchone()
        conn.commit()
        return str(row[0])


# ---------------------------------------------------------------------------
# Webhook dedup
# ---------------------------------------------------------------------------
def record_delivery_if_new(delivery_id: str) -> bool:
    """Returns True the first time a delivery id is seen, False on any
    replay. GitHub retries webhooks on any non-2xx response, so without this
    ledger a flaky worker double-inscribes decisions."""
    if not delivery_id:
        return True  # no id to dedup on (e.g. local curl test) — process it
    with get_conn() as conn:
        row = conn.execute(
            """
            insert into webhook_deliveries (delivery_id) values (%s)
            on conflict (delivery_id) do nothing
            returning delivery_id
            """,
            (delivery_id,),
        ).fetchone()
        conn.commit()
        return row is not None


# ---------------------------------------------------------------------------
# Idempotency keys (client-supplied, e.g. POST /v1/inscribe)
# ---------------------------------------------------------------------------
def get_idempotent_response(key: str) -> Optional[dict]:
    if not key:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "select response from idempotency_keys where key = %s", (key,)
        ).fetchone()
        return row[0] if row else None


def store_idempotent_response(key: str, tenant_id: Optional[str], response: dict) -> None:
    if not key:
        return
    with get_conn() as conn:
        conn.execute(
            """
            insert into idempotency_keys (key, tenant_id, response)
            values (%s, %s, %s)
            on conflict (key) do nothing
            """,
            (key, tenant_id, json.dumps(response)),
        )
        conn.commit()
