from __future__ import annotations

from fastapi import APIRouter, Response

from lore_backend.auth.keys import auth_enabled
from lore_backend.config import settings
from lore_backend.ingestion import github_client as gh
from lore_backend.memory import procedural
from lore_backend.metrics import render_prometheus
from lore_backend.obs import tracing
from lore_backend.retrieval import canon

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
