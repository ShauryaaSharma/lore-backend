"""Episodic memory — dated events, queried by time and id.

Postgres, because these questions are `order by occurred_at desc`, not
nearest-neighbour: "what did we ship last month", "what happened around the
outage", "have we been asked this before". Running them through embeddings
returns decisions that *sound* recent, which is a subtly wrong answer rather
than a slow one.

The control-plane database was already holding most of this (jobs,
installations, PRs) — this gives it a name and a retrieval path instead of
leaving it write-only.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.storage.db import get_conn

logger = logging.getLogger("lore.memory.episodic")


def record_event(scope: str, *, kind: str, source: str, title: str = "",
                 body: str = "", author: str = "", repo: str = "",
                 url: str = "", occurred_at: Optional[str] = None) -> int:
    """Append one raw event. Idempotent per (scope, source): a redelivered
    webhook updates the record rather than duplicating the decision.

    Re-ingesting resets `consolidated_at`, because a PR whose body changed
    needs distilling again."""
    with get_conn() as conn:
        row = conn.execute(
            """
            insert into decision_events
                (scope, kind, source, title, body, author, repo, url, occurred_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (scope, source) do update set
                title = excluded.title, body = excluded.body,
                author = excluded.author, repo = excluded.repo,
                url = excluded.url, occurred_at = excluded.occurred_at,
                consolidated_at = null
            returning id
            """,
            (scope, kind, source, title[:500], body, author, repo, url,
             occurred_at or None),
        ).fetchone()
        conn.commit()
        return int(row[0])


def recent(scope: str, limit: int = 10, since_days: Optional[int] = None) -> list[dict]:
    """Most recent decisions by when they happened — not when we indexed
    them, and not by similarity."""
    sql = """
        select source, title, body, author, repo, url, occurred_at, kind
        from decision_events
        where scope = %s
    """
    params: list = [scope]
    if since_days:
        sql += " and occurred_at >= now() - (interval '1 day' * %s)"
        params.append(since_days)
    sql += " order by occurred_at desc nulls last, id desc limit %s"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_event(r) for r in rows]


def pending_consolidation(scope: str, limit: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            select source, title, body, author, repo, url, occurred_at, kind
            from decision_events
            where scope = %s and consolidated_at is null
            order by id limit %s
            """,
            (scope, limit),
        ).fetchall()
    return [_row_to_event(r) for r in rows]


def pending_count(scope: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "select count(*) from decision_events "
            "where scope = %s and consolidated_at is null",
            (scope,),
        ).fetchone()
    return int(row[0])


def scopes_with_pending(min_events: int) -> list[tuple[str, int]]:
    """Which tenants have enough unconsolidated events to be worth a
    summarizer run. Drives the periodic job without it having to guess."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            select scope, count(*) as n from decision_events
            where consolidated_at is null
            group by scope having count(*) >= %s
            order by n desc
            """,
            (min_events,),
        ).fetchall()
    return [(r[0], int(r[1])) for r in rows]


def mark_consolidated(scope: str, sources: list[str]) -> int:
    if not sources:
        return 0
    with get_conn() as conn:
        cur = conn.execute(
            "update decision_events set consolidated_at = now() "
            "where scope = %s and source = any(%s)",
            (scope, list(sources)),
        )
        conn.commit()
        return cur.rowcount


def record_query(scope: str, *, question: str, answer: str, sources: list,
                 hops: int = 0, latency_ms: int = 0,
                 trace_id: Optional[str] = None, path: str = "agent") -> None:
    """Log an answered /why. Best-effort — a logging failure must not fail
    the request that just succeeded."""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                insert into why_queries
                    (scope, question, answer, sources, hops, latency_ms, trace_id, path)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (scope, question[:2000], answer[:8000], json.dumps(sources),
                 hops, latency_ms, trace_id, path),
            )
            conn.commit()
    except Exception:
        logger.exception("failed to record why_query (scope=%s)", scope)


def recent_queries(scope: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            select question, answer, sources, hops, latency_ms, path, created_at
            from why_queries where scope = %s
            order by created_at desc limit %s
            """,
            (scope, limit),
        ).fetchall()
    return [
        {"question": r[0], "answer": r[1], "sources": r[2], "hops": r[3],
         "latency_ms": r[4], "path": r[5], "created_at": r[6].isoformat()}
        for r in rows
    ]


def _row_to_event(r) -> dict:
    return {
        "source": r[0], "title": r[1], "body": r[2], "author": r[3],
        "repo": r[4], "url": r[5],
        "occurred_at": r[6].isoformat() if r[6] else None,
        "kind": r[7],
    }
