"""Semantic memory — durable, distilled decisions, searched by meaning.

This is the store mem0 used to wrap. It's called directly now because the
agent needs things mem0's managed `search()` doesn't hand back: the raw
similarity score, the stable decision id, and the untouched metadata — the
reranker needs the first, the citation guardrail needs the second, and the
answer's provenance needs the third. Consolidation, the other half of what
mem0 did, is now the summarizer agent's explicit job (see
`lore_backend.memory.consolidate`), so keeping both would have meant two systems
deciding what to remember and neither owning the result.

Embeddings stay local (fastembed, ONNX, CPU) — no key, no rate limit.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from lore_backend.config import settings

logger = logging.getLogger("lore.memory.semantic")

_embedder = None
_store = None

# Stable namespace so the same source (a PR, a commit) always maps to the
# same point id — re-ingesting a PR updates its decision instead of
# duplicating it.
_NS = uuid.UUID("6f1c1f6a-6e2b-4b5a-9a2f-1f3d5c7b9e11")


@dataclass
class Hit:
    """One retrieved decision. `id` is what the guardrail checks citations
    against; `score` is what the reranker rescores."""
    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0

    @property
    def source(self) -> str:
        return str(self.metadata.get("source") or "memory")

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "metadata": self.metadata,
                "score": round(float(self.score), 4)}


def point_id(scope: str, doc_id: str) -> str:
    return str(uuid.uuid5(_NS, f"{scope}:{doc_id}"))


def doc_id_for(source: str) -> str:
    """A decision's stable id, derived from its source label ("PR #482")."""
    slug = "".join(c if c.isalnum() else "-" for c in (source or "").lower()).strip("-")
    return slug or hashlib.sha256((source or "").encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# embedding
# --------------------------------------------------------------------------

def get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(model_name=settings.embedder_model)
    return _embedder


def embed(texts: list[str]) -> list[list[float]]:
    return [list(map(float, v)) for v in get_embedder().embed(texts)]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------

class QdrantStore:
    """Embedded (on-disk) by default — zero infra for a self-hoster. Point
    `QDRANT_URL` at a server to share one Canon across processes."""

    def __init__(self) -> None:
        from qdrant_client import QdrantClient

        self.server_mode = bool(settings.qdrant_url)
        if self.server_mode:
            self.client = QdrantClient(url=settings.qdrant_url,
                                       api_key=settings.qdrant_api_key or None)
        else:
            self.client = QdrantClient(path=settings.qdrant_path)
        self.collection = f"lore_{settings.embedder_dims}"
        self._ensure()

    def _ensure(self) -> None:
        from qdrant_client import models

        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=settings.embedder_dims,
                distance=models.Distance.COSINE,
            ),
        )
        # Scope is the tenant boundary — every read filters on it, so on a
        # real server it wants an index rather than a scan. Embedded Qdrant
        # ignores payload indexes (and warns), so don't ask for one there.
        if self.server_mode:
            self.client.create_payload_index(
                collection_name=self.collection,
                field_name="scope",
                field_schema="keyword",
            )

    def upsert(self, scope: str, doc_id: str, text: str, metadata: dict) -> str:
        from qdrant_client import models

        pid = point_id(scope, doc_id)
        self.client.upsert(
            collection_name=self.collection,
            points=[models.PointStruct(
                id=pid,
                vector=embed_one(text),
                payload={"scope": scope, "doc_id": doc_id, "text": text, **metadata},
            )],
        )
        return pid

    def _scope_filter(self, scope: str):
        from qdrant_client import models
        return models.Filter(must=[models.FieldCondition(
            key="scope", match=models.MatchValue(value=scope))])

    def search(self, scope: str, query: str, limit: int) -> list[Hit]:
        vector = embed_one(query)
        flt = self._scope_filter(scope)
        try:
            resp = self.client.query_points(
                collection_name=self.collection, query=vector,
                query_filter=flt, limit=limit, with_payload=True,
            )
            points = resp.points
        except AttributeError:  # qdrant-client < 1.10
            points = self.client.search(
                collection_name=self.collection, query_vector=vector,
                query_filter=flt, limit=limit, with_payload=True,
            )
        return [_hit_from_payload(p.payload or {}, p.score) for p in points]

    def all(self, scope: str, limit: int = 1000) -> list[Hit]:
        points, _ = self.client.scroll(
            collection_name=self.collection, scroll_filter=self._scope_filter(scope),
            limit=limit, with_payload=True,
        )
        return [_hit_from_payload(p.payload or {}, 0.0) for p in points]

    def rename(self, scope: str, old_doc_id: str, new_doc_id: str, new_source: str) -> bool:
        """Move a point to its new id, keeping its vector. False when there
        was nothing under the old id."""
        from qdrant_client import models

        old_pid, new_pid = point_id(scope, old_doc_id), point_id(scope, new_doc_id)
        found = {str(p.id): p for p in self.client.retrieve(
            collection_name=self.collection, ids=[old_pid, new_pid],
            with_payload=True, with_vectors=True)}
        if old_pid not in found:
            return False
        # Re-ingested since the upgrade: the new point is fresher, so the
        # old one just goes.
        if new_pid not in found:
            point = found[old_pid]
            payload = {**(point.payload or {}), "doc_id": new_doc_id, "source": new_source}
            self.client.upsert(collection_name=self.collection, points=[
                models.PointStruct(id=new_pid, vector=point.vector, payload=payload)])
        self.client.delete(collection_name=self.collection,
                           points_selector=models.PointIdsList(points=[old_pid]))
        return True


class PgVectorStore:
    """Same Canon, in the Postgres we already run. One connection string and
    one backup for the whole system, at the cost of Qdrant's filtering."""

    def __init__(self) -> None:
        self.table = f"canon_memories_{settings.embedder_dims}"
        self._ensure()

    def _ensure(self) -> None:
        # Created lazily rather than in migrations/: a plain Postgres without
        # the pgvector extension should still be able to run the control
        # plane, and only fail if it actually asks for a pgvector Canon.
        from lore_backend.storage.db import get_conn

        with get_conn() as conn:
            conn.execute("create extension if not exists vector")
            conn.execute(f"""
                create table if not exists {self.table} (
                    id text primary key,
                    scope text not null,
                    doc_id text not null,
                    text text not null,
                    metadata jsonb not null default '{{}}'::jsonb,
                    embedding vector({settings.embedder_dims}) not null,
                    updated_at timestamptz not null default now()
                )
            """)
            conn.execute(
                f"create index if not exists {self.table}_scope_idx on {self.table} (scope)"
            )
            conn.commit()

    def upsert(self, scope: str, doc_id: str, text: str, metadata: dict) -> str:
        import json

        from lore_backend.storage.db import get_conn

        pid = point_id(scope, doc_id)
        vec = "[" + ",".join(repr(x) for x in embed_one(text)) + "]"
        with get_conn() as conn:
            conn.execute(
                f"""
                insert into {self.table} (id, scope, doc_id, text, metadata, embedding)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (id) do update set
                    text = excluded.text, metadata = excluded.metadata,
                    embedding = excluded.embedding, updated_at = now()
                """,
                (pid, scope, doc_id, text, json.dumps(metadata), vec),
            )
            conn.commit()
        return pid

    def search(self, scope: str, query: str, limit: int) -> list[Hit]:
        from lore_backend.storage.db import get_conn

        vec = "[" + ",".join(repr(x) for x in embed_one(query)) + "]"
        with get_conn() as conn:
            rows = conn.execute(
                f"""
                select doc_id, text, metadata, 1 - (embedding <=> %s) as score
                from {self.table} where scope = %s
                order by embedding <=> %s limit %s
                """,
                (vec, scope, vec, limit),
            ).fetchall()
        return [Hit(id=r[0], text=r[1], metadata=r[2] or {}, score=float(r[3])) for r in rows]

    def all(self, scope: str, limit: int = 1000) -> list[Hit]:
        from lore_backend.storage.db import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                f"select doc_id, text, metadata from {self.table} "
                f"where scope = %s order by updated_at desc limit %s",
                (scope, limit),
            ).fetchall()
        return [Hit(id=r[0], text=r[1], metadata=r[2] or {}) for r in rows]

    def rename(self, scope: str, old_doc_id: str, new_doc_id: str, new_source: str) -> bool:
        import json

        from lore_backend.storage.db import get_conn

        old_pid, new_pid = point_id(scope, old_doc_id), point_id(scope, new_doc_id)
        with get_conn() as conn:
            # Re-ingested since the upgrade: the new row is fresher, so the
            # old one just goes.
            if conn.execute(f"select 1 from {self.table} where id = %s", (new_pid,)).fetchone():
                cur = conn.execute(f"delete from {self.table} where id = %s", (old_pid,))
            else:
                cur = conn.execute(
                    f"""
                    update {self.table}
                    set id = %s, doc_id = %s, metadata = metadata || %s::jsonb, updated_at = now()
                    where id = %s
                    """,
                    (new_pid, new_doc_id, json.dumps({"source": new_source}), old_pid),
                )
            conn.commit()
            return cur.rowcount > 0


def _hit_from_payload(payload: dict, score: float) -> Hit:
    payload = dict(payload)
    text = payload.pop("text", "")
    doc_id = payload.pop("doc_id", "")
    payload.pop("scope", None)
    return Hit(id=doc_id, text=text, metadata=payload, score=float(score or 0.0))


def get_store():
    global _store
    if _store is None:
        _store = PgVectorStore() if settings.vector_store == "pgvector" else QdrantStore()
    return _store


def reset_store_cache() -> None:
    """Tests swap backends between cases; production never calls this."""
    global _store, _embedder
    _store = None
    _embedder = None


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def remember(scope: str, *, text: str, source: str, metadata: Optional[dict] = None) -> str:
    """Write one decision. Idempotent per (scope, source) — re-ingesting a PR
    updates it in place rather than accumulating near-duplicates."""
    meta = {"source": source, **(metadata or {})}
    return get_store().upsert(scope, doc_id_for(source), text, meta)


def search(scope: str, query: str, limit: int = 20) -> list[Hit]:
    query = (query or "").strip()
    if not query:
        return []
    try:
        return get_store().search(scope, query, limit)
    except Exception:
        # A vector-store outage should degrade /why to "no record", not 500.
        logger.exception("semantic search failed (scope=%s)", scope)
        return []


def apply_source_renames(batch: int = 200) -> dict:
    """Carry decision renames recorded in Postgres (see migration 0004) over
    to the vector store. Called at startup by the API and the worker.

    Rows are claimed by stamping `applied_at` before the store is touched,
    so two processes starting together do not move the same point twice; a
    rename that fails is un-stamped and retried on the next start. Does not
    open the store at all when nothing is pending -- mock mode never wrote
    to it, and should not create one just to find it empty."""
    from lore_backend.storage.db import get_conn

    with get_conn() as conn:
        rows = conn.execute(
            """
            update source_renames set applied_at = now()
            where (scope, old_source) in (
                select scope, old_source from source_renames
                where applied_at is null limit %s for update skip locked)
            returning scope, old_source, new_source
            """,
            (batch,),
        ).fetchall()
        conn.commit()
    if not rows:
        return {"renamed": 0, "missing": 0, "failed": 0}

    renamed = missing = failed = 0
    store = get_store()
    for scope, old, new in rows:
        try:
            if store.rename(scope, doc_id_for(old), doc_id_for(new), new):
                renamed += 1
            else:
                missing += 1
        except Exception:
            logger.exception("vector store rename failed: %s -> %s (scope=%s)", old, new, scope)
            failed += 1
            with get_conn() as conn:
                conn.execute("update source_renames set applied_at = null "
                             "where scope = %s and old_source = %s", (scope, old))
                conn.commit()
    logger.info("applied source renames: %d moved, %d not in store, %d failed",
                renamed, missing, failed)
    return {"renamed": renamed, "missing": missing, "failed": failed}


def all_memories(scope: str, limit: int = 1000) -> list[Hit]:
    try:
        return get_store().all(scope, limit)
    except Exception:
        logger.exception("semantic listing failed (scope=%s)", scope)
        return []
