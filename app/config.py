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

    # --- Canon storage (vector memory) ---
    vector_store: Literal["qdrant", "pgvector"] = "qdrant"
    database_url: str = ""

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

    @property
    def mode(self) -> Literal["live", "mock"]:
        return "live" if self.groq_api_key else "mock"

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
