from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.ingestion.dedup import is_new_delivery
from app.ingestion.webhook_handler import (
    handle_installation_event,
    handle_pull_request_event,
    verify_github_signature,
)
from app.metrics import incr

logger = logging.getLogger("lore.webhook")

router = APIRouter()


@router.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
):
    """GitHub App webhook — auto-captures merged PRs into the Canon.

    Deduped on `X-GitHub-Delivery`: GitHub retries on any non-2xx response,
    so without this check a retry (or a slow request GitHub gave up on)
    would double-inscribe the same PR."""
    raw = await request.body()
    if not verify_github_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid signature")

    if not is_new_delivery(x_github_delivery):
        incr("webhook_duplicate_deliveries_total")
        return {"ok": True, "duplicate": True}

    if x_github_event == "ping":
        return {"ok": True, "pong": True}
    if x_github_event not in ("pull_request", "installation", "installation_repositories"):
        return {"ok": True, "ignored": x_github_event}

    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    incr(f"webhook_events_total{{event={x_github_event}}}")
    if x_github_event in ("installation", "installation_repositories"):
        return handle_installation_event(payload)
    return handle_pull_request_event(payload)
