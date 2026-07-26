"""The Canon — Lore's decision memory. Ported near-verbatim from the
prototype's `lore_engine.py`: mem0 (Groq LLM + fastembed embedder + a
swappable vector store) already gives us a clean, provider-agnostic RAG
layer, so this module keeps that shape rather than replacing it.

Two modes, chosen automatically from config:
  MOCK  (no GROQ_API_KEY)  — token-overlap retrieval over the seed corpus.
  LIVE  (GROQ_API_KEY set) — real mem0 memory, real GitHub PR ingestion,
                             cross-encoder reranked, LLM-composed cited
                             answers. See app/retrieval/rerank.py and
                             app/eval/ for the reranker and its regression
                             harness.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.retrieval.seed_decisions import SEED_DECISIONS
from app.retrieval.summarize import strip_bot_noise

_memory = None
_np_vector_adapter_done = False

_NO_MATCH = (
    "I don't have a recorded decision for that yet. In production, Lore keeps "
    "learning from every new PR, thread, and retro — so this gap fills itself "
    "over time. Try asking about auth, the database, microservices, or feature flags."
)


def account_scope(login: str) -> str:
    """The mem0 user_id under which an account's whole Canon lives."""
    return f"gh:{(login or '').strip().lower()}" if login else "demo"


def _vector_store_config() -> dict:
    collection = f"lore_{settings.embedder_dims}"
    if settings.vector_store == "pgvector":
        return {
            "provider": "pgvector",
            "config": {
                "connection_string": settings.database_url,
                "collection_name": collection,
                "embedding_model_dims": settings.embedder_dims,
            },
        }
    return {
        "provider": "qdrant",
        "config": {
            "collection_name": collection,
            "embedding_model_dims": settings.embedder_dims,
            "path": "qdrant_data",
        },
    }


def _register_numpy_vector_adapter() -> None:
    """psycopg3 can't hand a raw NumPy array to Postgres, but our local
    embedder (fastembed) returns NumPy arrays. Register a dumper that
    serialises them to pgvector's text form (`[1,2,3]`)."""
    global _np_vector_adapter_done
    if _np_vector_adapter_done:
        return
    try:
        import numpy as np
        import psycopg
        from psycopg.adapt import Dumper

        class _NumpyVectorDumper(Dumper):
            def dump(self, obj):
                return b"[" + b",".join(repr(float(x)).encode() for x in obj.tolist()) + b"]"

        psycopg.adapters.register_dumper(np.ndarray, _NumpyVectorDumper)
        _np_vector_adapter_done = True
    except Exception:
        pass


def get_memory():
    """Build the mem0 Memory on first use. LLM and embedder are independent,
    swappable knobs — moving Groq to another provider only touches the `llm`
    block, and mem0 already supports OpenAI/Anthropic/Ollama providers there."""
    global _memory
    if _memory is None:
        if settings.vector_store == "pgvector":
            _register_numpy_vector_adapter()
        from mem0 import Memory

        config = {
            "llm": {
                "provider": "groq",
                "config": {"model": settings.groq_model, "api_key": settings.groq_api_key},
            },
            "embedder": {
                "provider": "fastembed",
                "config": {"model": settings.embedder_model},
            },
            "vector_store": _vector_store_config(),
        }
        _memory = Memory.from_config(config)
    return _memory


def _tokenize(text: str) -> list[str]:
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


def status() -> dict:
    return {
        "mode": settings.mode,
        "llm": f"groq:{settings.groq_model}" if settings.mode == "live" else None,
        "embedder": f"fastembed:{settings.embedder_model}" if settings.mode == "live" else None,
        "canon_store": settings.vector_store,
        "decisions_in_seed": len(SEED_DECISIONS),
    }


def ingest_seed(scope: str) -> dict:
    if settings.mode == "mock":
        return {"mode": "mock", "ingested": len(SEED_DECISIONS),
                "note": "seed corpus is always searchable in mock mode"}
    mem = get_memory()
    n = 0
    for d in SEED_DECISIONS:
        source = d["sources"][0][1] if d["sources"] else d["title"]
        mem.add(d["answer"], user_id=scope, infer=False,
                metadata={"source": source, "title": d["title"], "area": d["meta"]})
        n += 1
    return {"mode": "live", "ingested": n}


def inscribe_pr(scope: str, *, number: int, title: str, body: str, threads: str,
                author: str, repo_full: str, url: str, merged_at: str) -> None:
    """Store a merged PR's discussion as a decision in the Canon."""
    clean_body = strip_bot_noise(body)
    clean_threads = strip_bot_noise(threads)
    text = f"PR #{number}: {title}" + (f"\n\n{clean_body}" if clean_body else "")
    if clean_threads:
        text += f"\n\nDiscussion:\n{clean_threads}"

    mem = get_memory()
    mem.add(text, user_id=scope, infer=False, metadata={
        "source": f"PR #{number}",
        "title": title[:80],
        "author": author,
        "canon": repo_full,
        "repo": repo_full,
        "url": url,
        "date": (merged_at or "")[:10],
    })


def inscribe_commit(commit: dict, scope: str) -> dict:
    """Inscribe a commit's reasoning (its `Why:`) into the Canon. Called by
    the Scribe (npm git hook). Only commits that declared a `Why:` reach
    here, so the Canon stays high-signal."""
    sha = str(commit.get("hash", ""))[:7] or "unknown"
    subject = (commit.get("message") or commit.get("subject") or "").strip()
    why = (commit.get("why") or "").strip()
    author = (commit.get("author") or "").strip()
    canon = (commit.get("repo") or commit.get("canon") or "").strip()

    text = f"{subject}\n\nWhy: {why}" if why else subject
    if not text.strip():
        return {"error": "empty commit"}
    if settings.mode == "mock":
        return {"mode": "mock", "inscribed": False,
                "note": "mock mode does not persist — set GROQ_API_KEY to inscribe"}

    mem = get_memory()
    mem.add(text, user_id=scope, infer=False, metadata={
        "source": f"commit {sha}", "title": subject[:80], "author": author, "canon": canon,
    })
    return {"mode": "live", "inscribed": True, "provenance": f"commit {sha}"}


def search_canon(query: str, scope: str, limit: int = 8) -> dict:
    """Free search across the Canon — matching Whys with provenance, without
    composing a narrative answer."""
    query = (query or "").strip()
    if not query:
        return {"mode": settings.mode, "count": 0, "results": []}

    if settings.mode == "mock":
        hit = _retrieve_seed(query)
        results = ([{"why": hit["answer"], "provenance": hit["sources"]}] if hit else [])
        return {"mode": "mock", "count": len(results), "results": results}

    mem = get_memory()
    res = mem.search(query, filters={"user_id": scope}, limit=limit)
    hits = res.get("results", []) if isinstance(res, dict) else (res or [])
    results = [{"why": h.get("memory", ""),
                "provenance": h.get("metadata", {}).get("source", "memory")} for h in hits]
    return {"mode": "live", "count": len(results), "results": results}


def list_memories(scope: str, cursor: int = 0, page_size: int = 50) -> dict:
    """Return what's stored, cursor-paginated (offset-based cursor is fine
    here — the Canon is append-mostly, not high-churn like a feed)."""
    if settings.mode == "mock":
        items = [{"memory": d["answer"],
                  "source": (d["sources"][0][1] if d["sources"] else d["title"])}
                 for d in SEED_DECISIONS]
        page = items[cursor:cursor + page_size]
        next_cursor = cursor + page_size if cursor + page_size < len(items) else None
        return {"mode": "mock", "count": len(items), "memories": page, "next_cursor": next_cursor}

    mem = get_memory()
    res = mem.get_all(filters={"user_id": scope})
    items = res.get("results", []) if isinstance(res, dict) else (res or [])
    out = [{"memory": m.get("memory", ""),
            "source": m.get("metadata", {}).get("source", "?")} for m in items]
    page = out[cursor:cursor + page_size]
    next_cursor = cursor + page_size if cursor + page_size < len(out) else None
    return {"mode": "live", "count": len(out), "memories": page, "next_cursor": next_cursor}


def answer_why(question: str, scope: str) -> dict:
    """Answer a /why question. Returns {answer, sources, mode, latency_s}."""
    t0 = time.time()
    question = (question or "").strip()
    if not question:
        return {"answer": "Ask me why something is built the way it is.",
                "sources": [], "mode": settings.mode, "latency_s": 0.0}

    if settings.mode == "mock":
        hit = _retrieve_seed(question)
        latency = round(time.time() - t0, 3)
        if not hit:
            return {"answer": _NO_MATCH, "sources": [], "mode": "mock", "latency_s": latency}
        return {"answer": hit["answer"], "sources": hit["sources"],
                "mode": "mock", "latency_s": latency}

    mem = get_memory()
    candidate_limit = settings.rerank_candidates if settings.rerank_enabled else settings.rerank_top_k
    results = mem.search(question, filters={"user_id": scope}, limit=candidate_limit)
    hits = results.get("results", []) if isinstance(results, dict) else (results or [])

    if settings.rerank_enabled and hits:
        from app.retrieval.rerank import rerank
        hits = rerank(question, hits, settings.rerank_top_k, lambda h: h.get("memory", ""))

    if not hits:
        return {"answer": _NO_MATCH, "sources": [], "mode": "live",
                "latency_s": round(time.time() - t0, 3)}

    def _line(h):
        m = h.get("metadata", {}) or {}
        body = strip_bot_noise(h.get("memory", ""))[:700].strip()
        if not body:
            return ""
        tags = " · ".join(t for t in (
            f"repo {m.get('repo') or m.get('canon')}" if (m.get("repo") or m.get("canon")) else "",
            f"merged {m.get('date')}" if m.get("date") else "",
        ) if t)
        head = f"[{tags}] " if tags else ""
        return f"- {head}{body} (source: {m.get('source', 'memory')})"
    context = "\n".join(line for line in (_line(h) for h in hits) if line)

    login = scope[3:] if scope.startswith("gh:") else scope
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = (
        "You are Lore, an engineering team's decision memory. Answer the question "
        "from the recorded decisions below.\n"
        f"- This Canon belongs to the GitHub account `{login}`; \"my repo\" or the "
        "account name refers to this user's own repositories.\n"
        f"- Today is {today} (UTC); resolve relative dates like \"yesterday\" or "
        "\"last week\" against each decision's `merged` date.\n"
        "- Reason across the decisions to connect casual phrasing to the right PR, "
        "explain the trade-offs, name who was involved if recorded, and cite sources "
        "inline like [PR #482]. Only say it isn't covered if nothing plausibly matches.\n\n"
        f"Recorded decisions:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    )

    from groq import Groq

    try:
        client = Groq(api_key=settings.groq_api_key)
        completion = client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        answer = completion.choices[0].message.content.strip()
    except Exception as e:
        return {
            "answer": f"⚠️ Groq call failed: {type(e).__name__}: {str(e)[:200]}. "
                      "Most likely an invalid/rotated GROQ_API_KEY, or Groq rate limits.",
            "sources": [], "mode": "live", "error": True,
            "latency_s": round(time.time() - t0, 3),
        }

    seen, sources = set(), []
    for h in hits:
        src = h.get("metadata", {}).get("source", "memory")
        if src in seen:
            continue
        seen.add(src)
        kind = "PR" if str(src).lower().startswith("pr") else "memory"
        sources.append([kind, src])

    cited = [s for s in sources if s[1] and s[1] in answer]
    sources = cited or sources[:2]

    return {"answer": answer, "sources": sources, "mode": "live",
            "latency_s": round(time.time() - t0, 3)}
