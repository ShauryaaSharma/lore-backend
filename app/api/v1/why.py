from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require_scope
from app.metrics import incr, timed
from app.retrieval import canon

router = APIRouter()


class WhyRequest(BaseModel):
    question: str
    user_id: str = "demo"


@router.post("/why")
def why(req: WhyRequest, scope: str = Depends(require_scope)):
    """Recall a decision — composed answer with provenance."""
    incr("why_requests_total")
    with timed("why_latency_seconds"):
        return canon.answer_why(req.question, scope)
