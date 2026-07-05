"""Postgres connection pool + a minimal migration runner.

No ORM: the control-plane schema is a handful of tables (tenants, api_keys,
installations, repos, jobs, webhook_deliveries, idempotency_keys) that don't
justify SQLAlchemy/Alembic. Migrations are plain numbered .sql files applied
in order, tracked in `schema_migrations`.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

from psycopg_pool import ConnectionPool

from app.config import settings

logger = logging.getLogger("lore.storage")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            open=True,
        )
    return _pool


@contextmanager
def get_conn():
    with get_pool().connection() as conn:
        yield conn


def run_migrations() -> list[str]:
    """Apply any .sql file under migrations/ not yet recorded, in filename
    order. Safe to call on every boot."""
    applied: list[str] = []
    with get_conn() as conn:
        conn.execute(
            """
            create table if not exists schema_migrations (
                filename text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        conn.commit()

        already = {
            row[0]
            for row in conn.execute("select filename from schema_migrations").fetchall()
        }

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in already:
                continue
            sql = path.read_text(encoding="utf-8")
            logger.info("applying migration %s", path.name)
            conn.execute(sql)
            conn.execute(
                "insert into schema_migrations (filename) values (%s)", (path.name,)
            )
            conn.commit()
            applied.append(path.name)
    return applied
