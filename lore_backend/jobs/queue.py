"""A Postgres-backed job queue: `SELECT ... FOR UPDATE SKIP LOCKED` to claim
work, no broker required. This is the Oban/GoodJob/River pattern — zero extra
infra for self-hosters, and it directly replaces the prototype's single
global `_backfill` dict + `threading.Thread`, which corrupted progress state
whenever two installs ran concurrently and lost all state on restart.

Job state (status, attempts, progress, error) now lives in the `jobs` table,
keyed by row id — independent per installation, and survives a process
restart (a `queued`/`running` job just gets picked up again).
"""

from __future__ import annotations

import json
from typing import Optional

from lore_backend.storage.db import get_conn


def enqueue(job_type: str, payload: dict, tenant_id: Optional[str] = None) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            insert into jobs (tenant_id, type, payload)
            values (%s, %s, %s)
            returning id
            """,
            (tenant_id, job_type, json.dumps(payload)),
        ).fetchone()
        conn.commit()
        return int(row[0])


def claim_next(job_types: tuple[str, ...]) -> Optional[dict]:
    """Atomically claim one queued, due job of the given types. Returns None
    if nothing is claimable. `SKIP LOCKED` means multiple worker processes
    can poll the same table without claiming the same row twice."""
    with get_conn() as conn:
        row = conn.execute(
            """
            select id, tenant_id, type, payload, attempts
            from jobs
            where status = 'queued' and run_after <= now() and type = any(%s)
            order by id
            for update skip locked
            limit 1
            """,
            (list(job_types),),
        ).fetchone()
        if not row:
            return None
        job_id = row[0]
        conn.execute(
            """
            update jobs set status = 'running', attempts = attempts + 1, updated_at = now()
            where id = %s
            """,
            (job_id,),
        )
        conn.commit()
        return {
            "id": job_id,
            "tenant_id": str(row[1]) if row[1] else None,
            "type": row[2],
            "payload": row[3],
            "attempts": row[4] + 1,
        }


def update_progress(job_id: int, progress: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "update jobs set progress = %s, updated_at = now() where id = %s",
            (json.dumps(progress), job_id),
        )
        conn.commit()


def mark_done(job_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "update jobs set status = 'done', updated_at = now() where id = %s",
            (job_id,),
        )
        conn.commit()


def mark_error(job_id: int, error: str, max_attempts: int, attempts: int) -> None:
    """Requeue with backoff if attempts remain, otherwise fail permanently."""
    with get_conn() as conn:
        if attempts < max_attempts:
            conn.execute(
                """
                update jobs
                set status = 'queued', error = %s,
                    run_after = now() + (interval '1 second' * (2 ^ %s)),
                    updated_at = now()
                where id = %s
                """,
                (error, attempts, job_id),
            )
        else:
            conn.execute(
                "update jobs set status = 'error', error = %s, updated_at = now() where id = %s",
                (error, job_id),
            )
        conn.commit()


def get_job(job_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            """
            select id, tenant_id, type, payload, status, attempts, progress, error
            from jobs where id = %s
            """,
            (job_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "tenant_id": str(row[1]) if row[1] else None,
            "type": row[2], "payload": row[3], "status": row[4],
            "attempts": row[5], "progress": row[6], "error": row[7],
        }


def get_jobs_for_installation(installation_id: int) -> list[dict]:
    """Recent jobs for one installation, so /v1/backfill/status can report
    per-installation progress instead of one shared global slot."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            select id, type, status, attempts, progress, error, created_at
            from jobs
            where payload->>'installation_id' = %s
            order by id desc
            limit 10
            """,
            (str(installation_id),),
        ).fetchall()
        return [
            {
                "id": r[0], "type": r[1], "status": r[2], "attempts": r[3],
                "progress": r[4], "error": r[5], "created_at": r[6].isoformat(),
            }
            for r in rows
        ]
