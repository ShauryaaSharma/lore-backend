"""Minimal Prometheus-format metrics — no external dependency, just enough
for a self-hoster to point Prometheus at `/metrics`. Full distributed
tracing (OpenTelemetry spans across services) isn't warranted yet: it's one
process, there's no service boundary to trace across."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)
_histograms: dict[str, list[float]] = defaultdict(list)


def incr(name: str, value: int = 1) -> None:
    with _lock:
        _counters[name] += value


def observe(name: str, value: float) -> None:
    with _lock:
        bucket = _histograms[name]
        bucket.append(value)
        if len(bucket) > 1000:  # bound memory; this is a cheap sample, not a real TSDB
            del bucket[: len(bucket) - 1000]


class timed:
    """`with timed("why_latency_seconds"): ...`"""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        observe(self.name, time.perf_counter() - self._t0)


def render_prometheus() -> str:
    lines = []
    with _lock:
        for name, value in sorted(_counters.items()):
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")
        for name, samples in sorted(_histograms.items()):
            if not samples:
                continue
            count = len(samples)
            total = sum(samples)
            lines.append(f"# TYPE {name} summary")
            lines.append(f"{name}_count {count}")
            lines.append(f"{name}_sum {total:.6f}")
            lines.append(f"{name}_avg {total / count:.6f}")
    return "\n".join(lines) + "\n"
