"""Webhook delivery dedup — GitHub retries a webhook on any non-2xx response,
so without this ledger a flaky worker (or a slow request that GitHub times
out on and retries) double-inscribes the same PR."""

from __future__ import annotations

from app.storage.queries import record_delivery_if_new


def is_new_delivery(delivery_id: str) -> bool:
    return record_delivery_if_new(delivery_id)
