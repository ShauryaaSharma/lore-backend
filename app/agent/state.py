"""Graph state — what flows between nodes during one /why run.

Everything here is ephemeral. Nothing is written back to a store directly
from state: anything worth keeping has to go through the memory layer, which
is what keeps "the agent remembered something" from meaning "some dict grew
a key nobody owns".
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import BaseMessage


def _keep_last(a: Any, b: Any) -> Any:
    """Last write wins. LangGraph needs a reducer for any key more than one
    node can set; for scalars the newer value is simply the right one."""
    return b if b is not None else a


class GraphState(TypedDict, total=False):
    # --- inputs, fixed for the run ---
    question: str
    scope: str          # tenant boundary — set from the API key, never by the model
    login: str

    # --- conversation with the model ---
    messages: Annotated[list[BaseMessage], operator.add]

    # --- loop control ---
    hops: Annotated[int, operator.add]
    stop_reason: Annotated[Optional[str], _keep_last]

    # --- what retrieval actually returned, accumulated across hops.
    # The guardrail checks the answer against this, so it has to be the real
    # retrieved set and not a summary of it. ---
    retrieved: Annotated[list[dict], operator.add]

    # --- outputs ---
    answer: Annotated[Optional[str], _keep_last]
    sources: Annotated[Optional[list], _keep_last]
    guardrail: Annotated[Optional[dict], _keep_last]
