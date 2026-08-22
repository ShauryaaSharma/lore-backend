"""The event shape shared by producer.py and consumer.py — the same fields
`lore_backend.ingestion.webhook_handler.handle_pull_request_event` reads off a real
GitHub payload, flattened into one dict so a streaming producer doesn't need
to know anything about GitHub's webhook schema."""

from __future__ import annotations

from typing import TypedDict


class PrMergedEvent(TypedDict):
    repo_full: str
    number: int
    title: str
    body: str
    author: str
    url: str
    merged_at: str


def sample_event() -> PrMergedEvent:
    return PrMergedEvent(
        repo_full="lorehasit/lore-backend",
        number=42,
        title="Add retry with backoff to the GitHub client",
        body="Flaky installation-token calls were failing hard on the first "
             "timeout. This adds jittered backoff, capped at 4 attempts.",
        author="octocat",
        url="https://github.com/lorehasit/lore-backend/pull/42",
        merged_at="2026-07-20T10:15:00Z",
    )
