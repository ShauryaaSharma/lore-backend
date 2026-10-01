from __future__ import annotations

from fastapi import APIRouter

from lore_backend.api.v1 import backfill, canon, inscribe, keys, why

router = APIRouter(prefix="/v1")
router.include_router(why.router, tags=["why"])
router.include_router(canon.router, tags=["canon"])
router.include_router(inscribe.router, tags=["inscribe"])
router.include_router(backfill.router, tags=["backfill"])
router.include_router(keys.router, tags=["keys"])
