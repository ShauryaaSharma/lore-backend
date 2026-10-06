"""Per-key token bucket rate limiting, in-process. A single backend instance
is the deployment target at this scale (per the architecture plan — Redis is
the documented upgrade path once the backend runs as more than one process,
not needed yet)."""

from __future__ import annotations

import threading
import time

from lore_backend.config import settings


class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, tokens: float, last_refill: float):
        self.tokens = tokens
        self.last_refill = last_refill


class TokenBucketLimiter:
    def __init__(self, requests_per_minute: int):
        self.capacity = max(1, requests_per_minute)
        self.refill_rate = self.capacity / 60.0  # tokens per second
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity - 1, last_refill=now)
                self._buckets[key] = bucket
                return True
            elapsed = now - bucket.last_refill
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_rate)
            bucket.last_refill = now
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True
            return False


limiter = TokenBucketLimiter(settings.rate_limit_requests_per_minute)
