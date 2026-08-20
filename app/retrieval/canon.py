"""The Canon — Lore's decision memory, and the entry point for `/why`.

This module used to be a fixed pipeline over mem0: embed, search, rerank,
prompt, return. It now sits on the three-tier memory layer (`app.memory`)
and dispatches answering to whichever path is enabled:

  MOCK   (no GROQ_API_KEY)      — token-overlap over the seed corpus.
  AGENT  (default in LIVE)      — the LangGraph loop. Can fetch what the
                                  Canon lacks; guardrail rejects uncited
                                  answers. See app/agent/.
  PIPELINE (AGENT_LOOP_ENABLED=false)
                                — the v1 straight-line path, kept as a
                                  fallback and as the comparison baseline.
                                  Reads the same memory layer, so both are
                                  scored on the same golden set.

Writes are write-through: a merged PR lands in episodic memory (raw, dated,
authoritative) *and* semantic memory (so it's searchable immediately). The
summarizer agent later distils the raw text and marks the event consolidated
— compaction, not the ingest path's critical section. A PR you merged sixty
seconds ago should be answerable now, not after the next batch job.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.memory import episodic, procedural, semantic
from app.retrieval.seed_decisions import SEED_DECISIONS
from app.retrieval.summarize import strip_bot_noise

logger = logging.getLogger("lore.canon")

_NO_MATCH = (
    "I don't have a recorded decision for that yet. In production, Lore keeps "
    "learning from every new PR, thread, and retro — so this gap fills itself "
    "over time. Try asking about auth, the database, microservices, or feature flags."
)


def account_scope(login: str) -> str:
    """The tenant key an account's whole Canon lives under."""
    return f"gh:{(login or '').strip().lower()}" if login else "demo"


def _login_from_scope(scope: str) -> str:
    return scope[3:] if scope.startswith("gh:") else scope


def status() -> dict:
    return {
        "mode": settings.mode,
        "path": _active_path(),
        "llm": f"groq:{settings.groq_model}" if settings.mode == "live" else None,
        "embedder": f"fastembed:{settings.embedder_model}" if settings.mode == "live" else None,
        "canon_store": settings.vector_store,
        "max_hops": settings.agent_max_hops if _active_path() == "agent" else None,
        "decisions_in_seed": len(SEED_DECISIONS),
    }


def _active_path() -> str:
    if settings.mode == "mock":
        return "mock"
    return "agent" if settings.agent_loop_enabled else "pipeline"


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------

def ingest_seed(scope: str) -> dict:
    if settings.mode == "mock":
        return {"mode": "mock", "ingested": len(SEED_DECISIONS),
                "note": "seed corpus is always searchable in mock mode"}
    n = 0
    for d in SEED_DECISIONS:
        source = d["sources"][0][1] if d["sources"] else d["title"]
        semantic.remember(scope, text=d["answer"], source=source,
                          metadata={"title": d["title"], "area": d["meta"]})
        episodic.record_event(scope, kind="seed", source=source,
                              title=d["title"], body=d["answer"])
        n += 1
    return {"mode": "live", "ingested": n}


def inscribe_pr(scope: str, *, number: int, title: str, body: str, threads: str,
                author: str, repo_full: str, url: str, merged_at: str) -> None:
    """Store a merged PR's discussion as a decision."""
    clean_body = strip_bot_noise(body)
    clean_threads = strip_bot_noise(threads)
    text = f"PR #{number}: {title}" + (f"\n\n{clean_body}" if clean_body else "")
    if clean_threads:
        text += f"\n\nDiscussion:\n{clean_threads}"

    source = f"PR #{number}"
    metadata = {"title": title[:80], "author": author, "repo": repo_full,
                "canon": repo_full, "url": url, "date": (merged_at or "")[:10]}

    episodic.record_event(scope, kind="pr", source=source, title=title,
                          body=text, author=author, repo=repo_full, url=url,
                          occurred_at=merged_at or None)
    semantic.remember(scope, text=text, source=source, metadata=metadata)


def inscribe_commit(commit: dict, scope: str) -> dict:
    """Inscribe a commit's `Why:` — called by the Scribe (the git hook CLI).
    Only commits that declared a reason reach here, so the Canon stays
    high-signal."""
    sha = str(commit.get("hash", ""))[:7] or "unknown"
    subject = (commit.get("message") or commit.get("subject") or "").strip()
    why = (commit.get("why") or "").strip()
    author = (commit.get("author") or "").strip()
    repo = (commit.get("repo") or commit.get("canon") or "").strip()

    text = f"{subject}\n\nWhy: {why}" if why else subject
    if not text.strip():
        return {"error": "empty commit"}
    if settings.mode == "mock":
        return {"mode": "mock", "inscribed": False,
                "note": "mock mode does not persist — set GROQ_API_KEY to inscribe"}

    source = f"commit {sha}"
    episodic.record_event(scope, kind="commit", source=source, title=subject,
                          body=text, author=author, repo=repo)
    semantic.remember(scope, text=text, source=source,
                      metadata={"title": subject[:80], "author": author,
                                "repo": repo, "canon": repo})
    return {"mode": "live", "inscribed": True, "provenance": source}


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    import re
    return [t for t in re.sub(r"[^a-z0-9\s]", " ", text.lower()).split() if t]


def _retrieve_seed(query: str) -> Optional[dict]:
    q = _tokenize(query)
    best, best_score = None, 0
    for d in SEED_DECISIONS:
        score = 0
        for t in q:
            if t in d["keys"]:
                score += 3
            elif len(t) > 3 and any(k.startswith(t) for k in d["keys"]):
                score += 2
            if len(t) > 3 and t in d["title"].lower():
                score += 1
        if score > best_score:
            best, best_score = d, score
    return best if best_score > 0 else None


def search_canon(query: str, scope: str, limit: int = 8) -> dict:
    """Free search — matching decisions with provenance, no composed answer."""
    query = (query or "").strip()
    if not query:
        return {"mode": settings.mode, "count": 0, "results": []}

    if settings.mode == "mock":
        hit = _retrieve_seed(query)
        results = ([{"why": hit["answer"], "provenance": hit["sources"]}] if hit else [])
        return {"mode": "mock", "count": len(results), "results": results}

    hits = semantic.search(scope, query, limit=limit)
    results = [{"why": h.text, "provenance": h.source, "score": round(h.score, 4)}
               for h in hits]
    return {"mode": "live", "count": len(results), "results": results}


def list_memories(scope: str, cursor: int = 0, page_size: int = 50) -> dict:
    """What's stored, cursor-paginated (offset cursors are fine — the Canon
    is append-mostly, not a high-churn feed)."""
    if settings.mode == "mock":
        items = [{"memory": d["answer"],
                  "source": (d["sources"][0][1] if d["sources"] else d["title"])}
                 for d in SEED_DECISIONS]
    else:
        items = [{"memory": h.text, "source": h.source}
                 for h in semantic.all_memories(scope)]

    page = items[cursor:cursor + page_size]
    next_cursor = cursor + page_size if cursor + page_size < len(items) else None
    return {"mode": settings.mode, "count": len(items), "memories": page,
            "next_cursor": next_cursor}


def answer_why(question: str, scope: str) -> dict:
    """Answer a /why question. {answer, sources, mode, latency_s, ...}."""
    t0 = time.time()
    question = (question or "").strip()
    if not question:
        return {"answer": "Ask me why something is built the way it is.",
                "sources": [], "mode": settings.mode, "path": _active_path(),
                "latency_s": 0.0}

    if settings.mode == "mock":
        result = _answer_mock(question, t0)
    elif settings.agent_loop_enabled:
        from app.agent import graph

        result = graph.run(question, scope)
    else:
        result = _answer_pipeline(question, scope, t0)

    # Recorded for every path, mock included: this is episodic memory of the
    # *asking*, and the questions Lore keeps failing to answer are where the
    # next ingestion gap is — that's as true in a demo as in production.
    episodic.record_query(
        scope, question=question, answer=result.get("answer", ""),
        sources=result.get("sources") or [], hops=result.get("hops", 0),
        latency_ms=int(result.get("latency_s", 0) * 1000),
        trace_id=result.get("trace_id"), path=result.get("path", "pipeline"),
    )
    return result


def _answer_mock(question: str, t0: float) -> dict:
    hit = _retrieve_seed(question)
    latency = round(time.time() - t0, 3)
    if not hit:
        return {"answer": _NO_MATCH, "sources": [], "mode": "mock",
                "path": "mock", "latency_s": latency}
    return {"answer": hit["answer"], "sources": hit["sources"], "mode": "mock",
            "path": "mock", "latency_s": latency}


def _answer_pipeline(question: str, scope: str, t0: float) -> dict:
    """The v1 straight-line path: search, rerank, compose. Kept so the loop
    has a baseline to be measured against — same store, same prompts, one
    LLM call and no tools."""
    candidate_limit = (settings.rerank_candidates if settings.rerank_enabled
                       else settings.rerank_top_k)
    hits = semantic.search(scope, question, limit=candidate_limit)

    if settings.rerank_enabled and hits:
        from app.retrieval.rerank import rerank
        hits = rerank(question, hits, settings.rerank_top_k, lambda h: h.text)

    if not hits:
        return {"answer": _NO_MATCH, "sources": [], "mode": "live",
                "path": "pipeline", "latency_s": round(time.time() - t0, 3)}

    context = "\n".join(line for line in (_context_line(h) for h in hits) if line)
    login = _login_from_scope(scope)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system = procedural.pipeline_prompt(login, today)
    prompt = f"Recorded decisions:\n{context}\n\nQuestion: {question}\n\nAnswer:"

    from groq import Groq

    try:
        client = Groq(api_key=settings.groq_api_key)
        completion = client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            temperature=settings.agent_temperature,
        )
        answer = completion.choices[0].message.content.strip()
    except Exception as e:
        return {
            "answer": f"⚠️ Groq call failed: {type(e).__name__}: {str(e)[:200]}. "
                      "Most likely an invalid/rotated GROQ_API_KEY, or Groq rate limits.",
            "sources": [], "mode": "live", "path": "pipeline", "error": True,
            "latency_s": round(time.time() - t0, 3),
        }

    # The pipeline gets the same citation check the agent does — an uncited
    # answer is no more shippable just because a different path produced it.
    from app.agent import guardrail

    retrieved = [{"source": h.source, "text": h.text, "metadata": h.metadata}
                 for h in hits]
    verdict = guardrail.check(answer, retrieved)
    if not verdict["ok"]:
        return {"answer": guardrail.failure_message(verdict, retrieved), "sources": [],
                "mode": "live", "path": "pipeline", "guardrail": verdict["status"],
                "latency_s": round(time.time() - t0, 3)}

    sources = []
    for source in verdict["matched"]:
        kind = "PR" if str(source).lower().startswith("pr") else "memory"
        sources.append([kind, source])

    return {"answer": answer, "sources": sources, "mode": "live", "path": "pipeline",
            "guardrail": verdict["status"], "latency_s": round(time.time() - t0, 3)}


def _context_line(hit) -> str:
    m = hit.metadata or {}
    body = strip_bot_noise(hit.text)[:700].strip()
    if not body:
        return ""
    tags = " · ".join(t for t in (
        f"repo {m.get('repo') or m.get('canon')}" if (m.get("repo") or m.get("canon")) else "",
        f"merged {m.get('date')}" if m.get("date") else "",
    ) if t)
    head = f"[{hit.source}]" + (f" ({tags})" if tags else "")
    return f"- {head} {body}"
