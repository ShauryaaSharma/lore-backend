"""API key issuance/revocation. Guarded by a separate admin secret rather
than the multi-tenant key scheme itself — there's no end-user login yet, so
this is the actual trust boundary for minting new tenant credentials."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.auth.keys import create_key, revoke
from app.config import settings

router = APIRouter()


class CreateKeyRequest(BaseModel):
    tenant_name: str
    scopes: list[str] = ["read:why", "admin:backfill"]


def _require_admin(x_admin_secret: str) -> None:
    if not settings.lore_admin_secret:
        raise HTTPException(status_code=503,
                            detail="key management disabled — set LORE_ADMIN_SECRET")
    if not x_admin_secret or x_admin_secret != settings.lore_admin_secret:
        raise HTTPException(status_code=401, detail="invalid admin secret")


@router.post("/keys")
def create_api_key(req: CreateKeyRequest, x_admin_secret: str = Header(None)):
    _require_admin(x_admin_secret)
    raw_key, tenant_id = create_key(req.tenant_name, req.scopes)
    return {"tenant_id": tenant_id, "api_key": raw_key,
            "note": "store this now — it will not be shown again"}


@router.delete("/keys/{key_id}")
def revoke_api_key(key_id: str, x_admin_secret: str = Header(None)):
    _require_admin(x_admin_secret)
    revoke(key_id)
    return {"ok": True, "revoked": key_id}
