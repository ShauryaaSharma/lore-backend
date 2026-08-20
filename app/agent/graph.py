"""The StateGraph: agent → tools → agent → guardrail.

Why a graph rather than a `while` loop with an `if`: the hop cap, the
per-node tracing, and the "what did it do before it got this wrong" replay
all want the control flow to be a thing you can inspect, not an emergent
property of nested conditionals. The loop is the part of this system most
likely to misbehave, so it's the part that should be most explicit.

    START → agent ─┬─(tool calls, hops left)→ tools → agent
                   └─(answer, or out of hops)→ guardrail → END
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.agent.guardrail import check as guardrail_check
from app.agent.guardrail import failure_message
from app.agent.state import GraphState
from app.agent.tools import Collector, build_tools
from app.config import settings
from app.memory import procedural
from app.metrics import incr
from app.obs import tracing

logger = logging.getLogger("lore.agent")


def get_llm(tools=None):
    """Groq via LangChain. Bound to tools when the caller has them — the
    same model object answers both with and without."""
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=settings.agent_temperature,
        max_retries=2,
    )
    return llm.bind_tools(tools) if tools else llm


def build_graph(scope: str, login: str, collector: Collector,
                allow_writes: bool = False, trace: Optional[tracing.Trace] = None):
    """Compile a graph for one run.

    Per-run rather than once at import because the tools close over the
    caller's scope — see app/agent/tools.py. Compilation is cheap; a tenant
    leak is not."""
    tools = build_tools(scope, login, collector, allow_writes=allow_writes)
    tools_by_name = {t.name: t for t in tools}
    llm = get_llm(tools)
    t = trace or tracing.Trace(None, "")

    def agent_node(state: GraphState) -> dict:
        messages = state["messages"]
        t0 = time.perf_counter()
        try:
            reply = llm.invoke(messages)
        except Exception as exc:
            logger.exception("agent LLM call failed")
            incr("agent_llm_errors_total")
            t.event("llm_error", error=f"{type(exc).__name__}: {exc}")
            return {
                "messages": [AIMessage(content="")],
                "stop_reason": f"llm_error:{type(exc).__name__}",
            }

        t.event("llm_call", ms=round((time.perf_counter() - t0) * 1000),
                tool_calls=[tc["name"] for tc in (reply.tool_calls or [])])
        return {"messages": [reply]}

    def tools_node(state: GraphState) -> dict:
        last = state["messages"][-1]
        out_messages, retrieved_before = [], len(collector.hits)

        for call in last.tool_calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                content = f"No tool named {call['name']}."
            else:
                try:
                    content = tool.invoke(call["args"])
                except Exception as exc:
                    # A failing tool is information for the model, not a dead
                    # run — it can try a different angle or stop honestly.
                    logger.warning("tool %s failed: %s", call["name"], exc)
                    incr(f"agent_tool_errors_total{{tool={call['name']}}}")
                    content = f"{call['name']} failed: {type(exc).__name__}. Try another approach."
            incr(f"agent_tool_calls_total{{tool={call['name']}}}")
            out_messages.append(ToolMessage(content=str(content), tool_call_id=call["id"]))

        new_hits = collector.hits[retrieved_before:]
        t.event("tool_hop", tools=[c["name"] for c in last.tool_calls],
                new_hits=len(new_hits))
        return {"messages": out_messages, "hops": 1, "retrieved": new_hits}

    def guardrail_node(state: GraphState) -> dict:
        """Where an answer becomes shippable, or doesn't."""
        answer = ""
        for message in reversed(state["messages"]):
            if isinstance(message, AIMessage) and message.content:
                answer = str(message.content).strip()
                break

        retrieved = state.get("retrieved", [])
        result = guardrail_check(answer, retrieved)
        t.event("guardrail", status=result["status"], reason=result["reason"],
                matched=result["matched"])
        incr(f"guardrail_total{{status={result['status']}}}")

        if not result["ok"]:
            logger.info("guardrail rejected an answer: %s", result["reason"])
            return {"answer": failure_message(result, retrieved), "sources": [],
                    "guardrail": result,
                    "stop_reason": state.get("stop_reason") or "guardrail_rejected"}

        sources = _sources_for(result["matched"], retrieved)
        return {"answer": answer, "sources": sources, "guardrail": result,
                "stop_reason": state.get("stop_reason") or "answered"}

    def route(state: GraphState) -> str:
        """The only place the loop can continue. One branch, easy to audit."""
        last = state["messages"][-1]
        wants_tools = isinstance(last, AIMessage) and bool(last.tool_calls)
        if not wants_tools:
            return "guardrail"
        if state.get("hops", 0) >= settings.agent_max_hops:
            # Out of hops with tools still pending: stop and let the
            # guardrail judge what we have. Failing loud beats looping.
            incr("agent_hop_cap_hit_total")
            t.event("hop_cap_reached", hops=state.get("hops", 0))
            return "guardrail"
        return "tools"

    graph = StateGraph(GraphState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", "guardrail": "guardrail"})
    graph.add_edge("tools", "agent")
    graph.add_edge("guardrail", END)
    return graph.compile()


def _sources_for(matched: list[str], retrieved: list[dict]) -> list[list[str]]:
    """Provenance for the surfaces, in the shape they already expect:
    [kind, label]. Cited sources only — listing everything retrieved would
    imply the answer used it."""
    by_source = {h.get("source"): h for h in retrieved}
    out = []
    for source in matched:
        meta = (by_source.get(source) or {}).get("metadata", {})
        low = str(source).lower()
        kind = ("PR" if low.startswith("pr") else
                "commit" if low.startswith("commit") else
                "ADR" if low.startswith("adr") else "memory")
        entry = [kind, source]
        if meta.get("url"):
            entry.append(meta["url"])
        out.append(entry)
    return out


def run(question: str, scope: str, *, allow_writes: bool = False) -> dict:
    """Answer one question through the loop.

    Returns the same shape the v1 pipeline returned, plus `hops`,
    `guardrail`, and `trace_id` — so existing callers keep working and new
    ones can see what happened."""
    t0 = time.time()
    login = scope[3:] if scope.startswith("gh:") else scope
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    collector = Collector()

    with tracing.trace("why", scope=scope, user_input=question,
                       model=settings.groq_model,
                       prompts=procedural.fingerprint()) as t:
        graph = build_graph(scope, login, collector, allow_writes=allow_writes, trace=t)
        system = procedural.system_prompt(login, today, settings.agent_max_hops)

        try:
            final = graph.invoke({
                "question": question,
                "scope": scope,
                "login": login,
                "messages": [SystemMessage(content=system), HumanMessage(content=question)],
                "hops": 0,
                "retrieved": [],
            })
        except Exception as exc:
            logger.exception("agent run failed")
            incr("agent_runs_failed_total")
            t.update(output=None, level="ERROR",
                     status_message=f"{type(exc).__name__}: {exc}")
            return {
                "answer": "Something went wrong answering that. It's been logged — try again.",
                "sources": [], "mode": "live", "error": True, "hops": 0,
                "trace_id": t.id, "latency_s": round(time.time() - t0, 3),
            }

        answer = final.get("answer") or ""
        guardrail = final.get("guardrail") or {}
        latency = round(time.time() - t0, 3)

        t.update(output=answer, metadata={
            "hops": final.get("hops", 0),
            "guardrail": guardrail.get("status"),
            "tool_calls": collector.calls,
            "stop_reason": final.get("stop_reason"),
        })

        return {
            "answer": answer,
            "sources": final.get("sources") or [],
            "mode": "live",
            "path": "agent",
            "hops": final.get("hops", 0),
            "guardrail": guardrail.get("status"),
            "tool_calls": collector.calls,
            "trace_id": t.id,
            "latency_s": latency,
        }
