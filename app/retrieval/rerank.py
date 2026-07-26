"""Cross-encoder reranking over mem0's vector-search candidates.

Dense embedding search (fastembed, cosine similarity) ranks semantically
close text well but is blind to lexical precision — an exact PR number,
ticket id, or function name mentioned in the question often loses to a
paraphrase that "sounds" closer in embedding space. A cross-encoder scores
(query, candidate) pairs jointly and catches that, at the cost of being too
slow to run over the whole Canon — so it only rescores the shortlist vector
search already narrowed down (`rerank_candidates` in), keeping the best
`top_k` (`rerank_top_k` out) for the LLM prompt.

Uses fastembed's `TextCrossEncoder` (ONNX, CPU) — the same runtime already
pulled in for embeddings, so this doesn't grow the install.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from app.config import settings

T = TypeVar("T")

_reranker = None


def get_reranker():
    global _reranker
    if _reranker is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _reranker = TextCrossEncoder(model_name=settings.rerank_model)
    return _reranker


def rerank(query: str, hits: list[T], top_k: int, text_fn: Callable[[T], str]) -> list[T]:
    """Re-score `hits` against `query`, return the best `top_k` descending.

    `text_fn` extracts the text to score from a hit, so this doesn't need to
    agree with callers on a hit shape (mem0 result dicts vs. anything else)."""
    if not hits:
        return hits
    documents = [text_fn(h) for h in hits]
    scores = list(get_reranker().rerank(query, documents))
    scored = sorted(zip(hits, scores), key=lambda pair: pair[1], reverse=True)
    return [hit for hit, _ in scored[:top_k]]
