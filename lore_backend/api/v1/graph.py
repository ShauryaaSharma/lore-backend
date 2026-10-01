"""Decision graph endpoints: is a decision still in force, what led to it,
and which decisions shaped a file."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lore_backend.api.deps import require_scope
from lore_backend.ingestion.links import normalize_source
from lore_backend.memory import graph
from lore_backend.retrieval import decision_check

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
            detail="source must be a PR (`acme/api#482`, `PR #482`, `#482`, `482`) "
                   "or a commit (`commit 1a2b3c4`)",
        )
    try:
        normalized = graph.resolve_source(scope, normalized)
    except graph.AmbiguousSource as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": f"{exc.source} exists in more than one repository; "
                               "ask again with one of these",
                    "candidates": exc.candidates},
        ) from exc
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


@router.get("/stale")
def get_stale_decisions(
    limit: int = Query(20, ge=1, le=100),
    scope: str = Depends(require_scope),
):
    """Decisions still in force whose code has probably moved on: files
    deleted since, or most of them changed by PRs that never said they
    replaced it. A review queue, not a verdict -- each entry lists the PRs
    and files behind the flag."""
    decisions = graph.stale_decisions(scope, limit=limit)
    return {"count": len(decisions), "decisions": decisions}


class CheckRequest(BaseModel):
    files: list[str] = Field(..., min_length=1, max_length=500,
                             description="Paths the change touches, repository-relative")
    title: str = ""
    body: str = Field("", description="Change description; 'Supersedes #N' here is recognised")
    repo: str = Field("", description="owner/name, so a bare #N in the body means this repository")
    limit: int = Field(5, ge=1, le=20)


@router.post("/check")
def check_change(req: CheckRequest, scope: str = Depends(require_scope)):
    """The decision check the GitHub App runs on every opened PR, callable
    before there is a PR: from a pre-push hook, the CLI, or the editor."""
    return decision_check.check(scope, req.files, title=req.title, body=req.body,
                                repo=req.repo, limit=req.limit)


@router.post("/rebuild")
def rebuild(scope: str = Depends(require_scope)):
    """Re-derive every stored decision's links from its text. Use after
    upgrading, so decisions ingested before the graph existed get edges.
    Changed files come from GitHub at ingest time and are not rebuilt."""
    return graph.rebuild_links(scope)
