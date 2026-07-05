from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.api.deps import require_scope
from app.storage.queries import get_idempotent_response, store_idempotent_response

router = APIRouter()


class CommitPayload(BaseModel):
    hash: str = ""
    message: str = ""
    why: str = ""
    author: str = ""
    repo: str = ""
    branch: str = ""
    user_id: str = "demo"


@router.post("/inscribe")
def inscribe(c: CommitPayload, scope: str = Depends(require_scope),
            idempotency_key: str = Header(None, alias="Idempotency-Key")):
    """The Scribe inscribes a commit's Why into the Canon.

    Honors an `Idempotency-Key` header: a retried `npx lore` invocation
    after a network blip (the CLI has no way to know if the first attempt
    landed) returns the original result instead of writing the commit twice.
    """
    from app.retrieval.canon import inscribe_commit

    if idempotency_key:
        cached = get_idempotent_response(idempotency_key)
        if cached is not None:
            return cached

    result = inscribe_commit(c.model_dump(), scope)

    if idempotency_key:
        store_idempotent_response(idempotency_key, None, result)
    return result
