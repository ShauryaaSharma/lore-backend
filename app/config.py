"""Typed, validated configuration. One source of truth — every other module
imports `settings` from here instead of calling `os.getenv` directly.

Fails fast at boot (not lazily, mid-request) when a combination of settings
doesn't make sense — e.g. VECTOR_STORE=pgvector with no DATABASE_URL.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM (Groq) ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # --- Embeddings (local, free, no key) ---
    embedder_model: str = "thenlper/gte-large"
    embedder_dims: int = 1024

    # --- Reranking (local, free, no key) ---
    # Dense search alone loses exact-term matches (a PR number, a ticket id)
    # to paraphrases that "sound" closer. A cross-encoder rescoring the
    # shortlist catches that. Same runtime (fastembed, ONNX, CPU) as the
    # embedder, so this doesn't add a new dependency.
    rerank_enabled: bool = True
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = 20  # vector-search shortlist size, before rerank
    rerank_top_k: int = 6        # how many survive rerank into the LLM prompt

    # --- Semantic memory (the Canon's vector store) ---
    # Called directly (qdrant-client + fastembed), not through mem0: the
    # tools need raw scored hits with decision ids, and consolidation is the
    # summarizer agent's job. See docs/adr/0001-agentic-retrieval-*.md.
    vector_store: Literal["qdrant", "pgvector"] = "qdrant"
    qdrant_path: str = "qdrant_data"   # embedded/on-disk mode, zero infra
    qdrant_url: str = ""               # set to use a server instead of qdrant_path
    qdrant_api_key: str = ""
    database_url: str = ""

    # --- Agent harness (LangGraph) ---
    # The loop can go fetch what the Canon lacks instead of answering from a
    # stale shortlist. Flag it off to fall back to the v1 straight-line
    # pipeline — both read the same memory layer, so they're comparable on
    # the same golden set.
    agent_loop_enabled: bool = True
    agent_max_hops: int = 4            # a runaway loop should fail loud, not slow
    agent_temperature: float = 0.2

    # --- Procedural memory (prompts as files, not DB rows) ---
    prompts_dir: str = "prompts"

    # --- Consolidation (episodic -> semantic) ---
    summarizer_model: str = "llama-3.1-8b-instant"
    consolidate_after_n_events: int = 25
    consolidate_batch_size: int = 40
    consolidate_sweep_seconds: float = 300.0  # how often the worker looks for due tenants

    # --- GitHub App ---
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_app_private_key_path: str = ""
    github_webhook_secret: str = ""
    github_token: str = ""
    backfill_days: int = 15

    # --- Single-tenant fallback ---
    lore_default_account: str = ""

    # --- Multi-tenant auth env fallback (kept for zero-DB local/dev use;
    # production should create keys via POST /v1/keys, stored hashed in DB) ---
    lore_api_keys: str = ""

    # --- Admin bootstrap secret — required to call POST/DELETE /v1/keys.
    # There's no end-user login yet, so this is the trust boundary for key
    # management itself (chicken-and-egg: you need a key to make a key). ---
    lore_admin_secret: str = ""

    # --- Jobs / worker ---
    job_poll_interval_seconds: float = 2.0
    job_max_attempts: int = 5

    # --- Resilience ---
    http_timeout_seconds: float = 30.0
    retry_max_attempts: int = 4
    retry_base_delay_seconds: float = 0.5
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_cooldown_seconds: float = 30.0

    # --- Rate limiting ---
    rate_limit_requests_per_minute: int = 120

    # --- Observability ---
    log_level: str = "INFO"
    log_json: bool = True

    # --- LLM Ops (Langfuse, self-hosted) ---
    # Unset = tracing no-ops. Nothing in the request path depends on Langfuse
    # being reachable; a tracing outage must never fail a /why.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # --- Eval gate ---
    # The judge is observe-only until it's shown to correlate with human
    # judgment — run it, record the score, don't gate on it yet.
    judge_enabled: bool = False
    judge_model: str = "llama-3.3-70b-versatile"
    eval_hit_rate_floor: float = 0.9
    eval_citation_floor: float = 0.9

    @property
    def mode(self) -> Literal["live", "mock"]:
        return "live" if self.groq_api_key else "mock"

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @model_validator(mode="after")
    def _validate_combinations(self) -> "Settings":
        if self.vector_store == "pgvector" and not self.database_url:
            raise ValueError(
                "VECTOR_STORE=pgvector requires DATABASE_URL to be set"
            )
        # The control-plane (tenants/api_keys/jobs/...) always needs Postgres,
        # independent of which vector store backs the Canon.
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL is required — the control plane (auth, jobs, "
                "webhook dedup) lives in Postgres regardless of VECTOR_STORE"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
