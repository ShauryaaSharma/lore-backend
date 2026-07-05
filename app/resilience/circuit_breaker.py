"""A minimal circuit breaker: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

Prevents hammering a downstream that's already failing (Groq outage, GitHub
incident) — once `failure_threshold` consecutive failures happen, the breaker
trips OPEN and fails fast (no network call) for `cooldown_seconds`. After the
cooldown it lets exactly one call through (HALF_OPEN); success closes it,
failure re-opens it.

One breaker instance per downstream dependency (not shared across different
external services) — construct one per client.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised instead of calling the downstream while the breaker is OPEN."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0,
                name: str = "circuit"):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.name = name
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and self._opened_at is not None
                and time.time() - self._opened_at >= self.cooldown_seconds
            ):
                self._state = CircuitState.HALF_OPEN
            return self._state

    def _on_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    def _on_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if (
                self._state == CircuitState.HALF_OPEN
                or self._consecutive_failures >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = time.time()

    def call(self, fn: Callable[[], T]) -> T:
        current = self.state
        if current == CircuitState.OPEN:
            raise CircuitOpenError(f"{self.name} circuit is open")
        try:
            result = fn()
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result
