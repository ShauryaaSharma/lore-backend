"""Decision graph endpoints: is a decision still in force, what led to it,
and which decisions shaped a file."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from lore_backend.api.deps import require_scope
from lore_backend.ingestion.links import normalize_source
from lore_backend.memory import graph

router = APIRouter(prefix="/graph")


@router.get("/decision")
def get_decision(
    source: str = Query(..., min_length=1, description="`PR #482`, `#482`, `482`, or `commit 1a2b3c4`"),
    depth: int = Query(5, ge=1, le=graph.MAX_DEPTH, description="How far up and down the lineage to list"),
    scope: str = Depends(require_scope),
):
    """One decision: whether it still holds, what overturned it if not, the
    chain of decisions it replaced or was replaced by, every link in and
    out, and the files it changed."""
    normalized = normalize_source(source)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail="source must be a PR (`PR #482`, `#482`, `482`) or a commit (`commit 1a2b3c4`)",
        )
    found = graph.decision(scope, normalized, max_depth=depth)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no decision or link recorded for {normalized}")
    return found


@router.get("/files")
def get_decisions_for_path(
    path: str = Query(..., min_length=1, description="A file, or a directory to match everything under"),
    limit: int = Query(20, ge=1, le=100),
    scope: str = Depends(require_scope),
):
    """Decisions that changed a file or anything under a directory, newest
    first, each marked with whether it still holds."""
    decisions = graph.decisions_touching(scope, path, limit=limit)
    return {"path": path, "count": len(decisions), "decisions": decisions}


@router.post("/rebuild")
def rebuild(scope: str = Depends(require_scope)):
    """Re-derive every stored decision's links from its text. Use after
    upgrading, so decisions ingested before the graph existed get edges.
    Changed files come from GitHub at ingest time and are not rebuilt."""
    return graph.rebuild_links(scope)
