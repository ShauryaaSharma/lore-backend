from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lore_backend.api.deps import require_scope
from lore_backend.memory import episodic
from lore_backend.metrics import incr, observe, timed
from lore_backend.retrieval import canon

router = APIRouter()


class WhyRequest(BaseModel):
    question: str
    user_id: str = "demo"


@router.post("/why")
def why(req: WhyRequest, scope: str = Depends(require_scope)):
    """Recall a decision — composed answer with provenance.

    The response carries `path`, `hops`, `guardrail` and `trace_id` so a
    surface (or a support conversation) can tell *how* an answer was reached,
    not just what it said."""
    incr("why_requests_total")
    with timed("why_latency_seconds"):
        result = canon.answer_why(req.question, scope)

    incr(f"why_path_total{{path={result.get('path', 'unknown')}}}")
    if result.get("guardrail"):
        incr(f"why_guardrail_total{{status={result['guardrail']}}}")
    if result.get("hops"):
        observe("why_hops", float(result["hops"]))
    return result


@router.get("/why/history")
def why_history(limit: int = 20, scope: str = Depends(require_scope)):
    """Recently answered questions for this Canon — episodic memory of the
    asking, not of the decisions. Useful for spotting the questions Lore
    keeps failing to answer, which is where the next ingestion gap is."""
    return {"queries": episodic.recent_queries(scope, limit=min(limit, 100))}
