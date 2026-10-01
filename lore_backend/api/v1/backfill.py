from __future__ import annotations

from fastapi import APIRouter, Header

from lore_backend.api.deps import require_account

router = APIRouter()


@router.get("/backfill/status")
def backfill_status(installation_id: int):
    """Progress of the most recent backfill jobs for one installation — the
    extension's 'indexing…' indicator now reads per-installation job rows
    instead of a single shared global (the prototype's `_backfill` dict,
    which corrupted state under concurrent installs)."""
    from lore_backend.jobs.queue import get_jobs_for_installation

    return {"installation_id": installation_id,
            "jobs": get_jobs_for_installation(installation_id)}


@router.post("/backfill/run")
def backfill_run(account: str = "", authorization: str = Header(None),
                 x_lore_key: str = Header(None), key: str = ""):
    """Manually kick off a backfill for an already-installed account (no
    webhook needed). With auth on, the key's account is used and must match
    `account` if given."""
    from lore_backend.ingestion.webhook_handler import trigger_backfill

    account = require_account(account, authorization, x_lore_key, key)
    return trigger_backfill(account or None)
