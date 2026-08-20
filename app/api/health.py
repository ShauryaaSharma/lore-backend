from __future__ import annotations

from fastapi import APIRouter, Response

from app.auth.keys import auth_enabled
from app.config import settings
from app.ingestion import github_client as gh
from app.memory import procedural
from app.metrics import render_prometheus
from app.obs import tracing
from app.retrieval import canon

router = APIRouter()


@router.get("/health")
def health():
    return {
        "ok": True,
        **canon.status(),
        "auth": "multi-tenant" if auth_enabled() else "single-tenant",
        "default_account": None if auth_enabled() else (
            canon.account_scope(settings.lore_default_account)
            if settings.lore_default_account else None
        ),
        "github_app": gh.app_configured(),
        "backfill_days": settings.backfill_days,
        # Which prompt files are loaded, so a bad answer can be tied to the
        # procedural memory that produced it without shelling into the box.
        "prompts": procedural.fingerprint(),
        "tracing": tracing.status(),
    }


@router.get("/metrics")
def metrics():
    return Response(content=render_prometheus(), media_type="text/plain")
