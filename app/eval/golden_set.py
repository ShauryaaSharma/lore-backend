"""Golden Q&A set for the `/why` regression harness. Each case targets one
entry in `app.retrieval.seed_decisions.SEED_DECISIONS`, so the harness runs
deterministically in MOCK mode with zero API keys — this is a CI regression
gate against retrieval/reranking breakage, not an exhaustive quality
benchmark. Run it against LIVE mode (after `POST /v1/ingest/seed`) to see
the same questions through the real mem0 + rerank + Groq path."""

from __future__ import annotations

from typing import TypedDict


class GoldenCase(TypedDict):
    question: str
    decision_id: str             # must match a SEED_DECISIONS "id"
    must_cite: str                # substring expected in the returned sources
    must_include_any: list[str]   # answer should mention at least one of these


GOLDEN_SET: list[GoldenCase] = [
    {
        "question": "Why did we move away from server-side sessions?",
        "decision_id": "auth-tokens",
        "must_cite": "#482",
        "must_include_any": ["jwt", "redis", "session"],
    },
    {
        "question": "Why didn't we split into microservices?",
        "decision_id": "monolith",
        "must_cite": "ADR-007",
        "must_include_any": ["payments", "operational", "split"],
    },
    {
        "question": "Why Postgres instead of Mongo?",
        "decision_id": "postgres",
        "must_cite": "ADR-004",
        "must_include_any": ["relational", "schema", "jsonb"],
    },
    {
        "question": "Why did we go with SQS instead of running our own Kafka?",
        "decision_id": "queue",
        "must_cite": "ADR-009",
        "must_include_any": ["kafka", "sqs", "on-call"],
    },
    {
        "question": "Why did we build feature flags ourselves instead of buying LaunchDarkly?",
        "decision_id": "feature-flags",
        "must_cite": "ADR-011",
        "must_include_any": ["launchdarkly", "flag", "rollout"],
    },
    {
        "question": "Why is the marketing site server-rendered but the app is a SPA?",
        "decision_id": "rendering",
        "must_cite": "ADR-006",
        "must_include_any": ["seo", "ssr", "spa"],
    },
]
