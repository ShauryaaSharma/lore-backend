"""Worker entrypoint: `python -m lore_backend.jobs.worker`. A simple poll loop against
the Postgres-backed queue — deliberately not Celery/RQ/Temporal. At this
project's scale (a handful of tenants, install-time backfills, not a
continuous high-volume stream) a poll loop is the right amount of
infrastructure; upgrade to a broker only once this one demonstrably falls
behind."""

from __future__ import annotations

import logging
import time

from lore_backend.config import settings
from lore_backend.jobs import queue
from lore_backend.jobs.handlers import HANDLERS
from lore_backend.logging_setup import configure_logging
from lore_backend.storage.db import run_migrations

logger = logging.getLogger("lore.worker")


def run_forever() -> None:
    configure_logging()
    run_migrations()
    logger.info("worker started, polling every %.1fs", settings.job_poll_interval_seconds)
    next_sweep = 0.0
    while True:
        # Memory consolidation has no external trigger — nothing arrives to
        # say "this tenant has accumulated enough raw events". The worker
        # sweeps for it on an interval rather than the deployment growing a
        # cron sidecar for one periodic task.
        if time.monotonic() >= next_sweep:
            _sweep_consolidations()
            next_sweep = time.monotonic() + settings.consolidate_sweep_seconds

        job = queue.claim_next(tuple(HANDLERS.keys()))
        if job is None:
            time.sleep(settings.job_poll_interval_seconds)
            continue
        _run_job(job)


def _sweep_consolidations() -> None:
    from lore_backend.jobs.handlers import enqueue_due_consolidations

    try:
        enqueue_due_consolidations()
    except Exception:  # a failed sweep must not stop the worker draining jobs
        logger.exception("consolidation sweep failed")


def _run_job(job: dict) -> None:
    handler = HANDLERS.get(job["type"])
    if handler is None:
        queue.mark_error(job["id"], f"no handler for type={job['type']}",
                         settings.job_max_attempts, job["attempts"])
        return
    try:
        handler(job)
    except Exception as exc:  # never let the worker loop die on one bad job
        logger.exception("job %s failed (attempt %d)", job["id"], job["attempts"])
        queue.mark_error(job["id"], f"{type(exc).__name__}: {exc}",
                         settings.job_max_attempts, job["attempts"])
        return
    queue.mark_done(job["id"])


if __name__ == "__main__":
    run_forever()
