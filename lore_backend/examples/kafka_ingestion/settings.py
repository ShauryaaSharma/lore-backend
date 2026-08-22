"""Tiny, standalone settings for the Kafka demo. Deliberately not part of
`lore_backend.config.Settings` — the real app's settings module fails fast at import
time if required env vars are missing, and this demo shouldn't be able to
break that."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class KafkaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_topic: str = "lore.pr_merged"


kafka_settings = KafkaSettings()
