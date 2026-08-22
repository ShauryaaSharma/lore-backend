from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lore_backend.api.deps import require_scope
from lore_backend.retrieval import canon as canon_engine

router = APIRouter()


class LoreSearch(BaseModel):
    query: str
    user_id: str = "demo"


@router.get("/canon")
def get_canon(cursor: int = 0, page_size: int = 50, scope: str = Depends(require_scope)):
    """Everything currently in the Canon, cursor-paginated. The prototype
    returned everything in one response — fine for a handful of decisions,
    not once a real account has thousands of merged PRs indexed."""
    return canon_engine.list_memories(scope, cursor=cursor, page_size=page_size)


@router.get("/memories")
def memories(cursor: int = 0, page_size: int = 50, scope: str = Depends(require_scope)):
    return canon_engine.list_memories(scope, cursor=cursor, page_size=page_size)


@router.post("/lore")
def search_lore(req: LoreSearch, scope: str = Depends(require_scope)):
    """Free search across the Canon — matching Whys with provenance."""
    return canon_engine.search_canon(req.query, scope)


@router.post("/ingest/seed")
def ingest_seed(scope: str = Depends(require_scope)):
    return canon_engine.ingest_seed(scope)
