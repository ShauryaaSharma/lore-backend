"""Unit test for the reranking logic only — the cross-encoder scorer is
faked out via monkeypatch so this runs fast and offline, without pulling
down the ONNX model. app/examples/kafka_ingestion-style separation: model
loading is exercised manually, not in the default test run."""

from __future__ import annotations

import lore_backend.retrieval.rerank as rerank_mod

_STOPWORDS = {"why", "did", "we", "for", "the", "a", "over", "our", "to", "of"}


class _FakeReranker:
    """Scores a document higher the more non-stopword words it shares with
    the query — crude, but enough to prove `rerank()` reorders by score
    without pulling in stopword noise."""

    def rerank(self, query, documents):
        q_words = set(query.lower().split()) - _STOPWORDS
        for doc in documents:
            yield len(q_words & (set(doc.lower().split()) - _STOPWORDS))


def test_rerank_reorders_by_score(monkeypatch):
    monkeypatch.setattr(rerank_mod, "get_reranker", lambda: _FakeReranker())

    hits = [
        {"memory": "we picked postgres for the primary datastore"},
        {"memory": "we chose managed sqs over running kafka ourselves"},
        {"memory": "server-rendered marketing site, spa for the app"},
    ]

    ranked = rerank_mod.rerank(
        "why did we pick kafka for the queue",
        hits, top_k=2, text_fn=lambda h: h["memory"],
    )

    assert len(ranked) == 2
    assert ranked[0]["memory"] == "we chose managed sqs over running kafka ourselves"


def test_rerank_empty_hits_is_noop(monkeypatch):
    monkeypatch.setattr(rerank_mod, "get_reranker",
                         lambda: (_ for _ in ()).throw(AssertionError("should not be called")))
    assert rerank_mod.rerank("anything", [], top_k=5, text_fn=lambda h: h) == []


def test_rerank_top_k_truncates(monkeypatch):
    monkeypatch.setattr(rerank_mod, "get_reranker", lambda: _FakeReranker())
    hits = [{"memory": f"doc {i} kafka"} for i in range(10)]
    ranked = rerank_mod.rerank("kafka", hits, top_k=3, text_fn=lambda h: h["memory"])
    assert len(ranked) == 3
