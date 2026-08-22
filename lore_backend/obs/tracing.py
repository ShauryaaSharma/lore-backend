"""Tracing — one trace per graph run.

Wraps Langfuse behind a null object so the rest of the codebase never
branches on whether tracing is configured. Two rules hold everywhere in
here:

  1. Tracing never raises into the caller. A Langfuse outage degrades
     observability; it must not degrade /why.
  2. Tracing never blocks the answer. Spans are fire-and-forget; the flush
     happens at process shutdown, not per request.

Self-hosted by default: this data is a record of what an engineering team
argued about, which is exactly the kind of thing that shouldn't leave the
box.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Any, Optional

from lore_backend.config import settings

logger = logging.getLogger("lore.obs")

_client: Any = None
_init_failed = False


def get_client():
    """Lazily build the Langfuse client. Returns None when unconfigured or
    when the SDK isn't importable — both are normal (mock mode, CI)."""
    global _client, _init_failed
    if _client is not None or _init_failed:
        return _client
    if not settings.tracing_enabled:
        _init_failed = True
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception:
        logger.warning("langfuse unavailable — continuing without tracing", exc_info=True)
        _init_failed = True
        return None
    return _client


class NullSpan:
    """Same surface as a real span, does nothing. Lets call sites stay
    unconditional instead of `if trace: trace.update(...)`."""

    id: Optional[str] = None

    def event(self, **kwargs) -> None: ...
    def update(self, **kwargs) -> None: ...
    def score(self, **kwargs) -> None: ...
    def end(self, **kwargs) -> None: ...


class Trace:
    """One /why run. `id` is stored on the why_queries row so a bad answer in
    the database can be opened as a trace in the UI."""

    def __init__(self, handle: Any, trace_id: str) -> None:
        self._handle = handle
        self.id = trace_id

    def event(self, name: str, **payload) -> None:
        if self._handle is None:
            return
        try:
            self._handle.event(name=name, metadata=payload)
        except Exception:
            logger.debug("trace event failed", exc_info=True)

    def update(self, **payload) -> None:
        if self._handle is None:
            return
        try:
            self._handle.update(**payload)
        except Exception:
            logger.debug("trace update failed", exc_info=True)

    def score(self, name: str, value: float, comment: str = "") -> None:
        if self._handle is None:
            return
        try:
            self._handle.score(name=name, value=value, comment=comment or None)
        except Exception:
            logger.debug("trace score failed", exc_info=True)


@contextmanager
def trace(name: str, *, scope: str = "", user_input: str = "", **metadata):
    """Open a trace for one run. Always yields a Trace — a null one when
    tracing is off — so callers never special-case it."""
    trace_id = uuid.uuid4().hex
    client = get_client()
    handle = None
    if client is not None:
        try:
            handle = client.trace(
                id=trace_id, name=name, user_id=scope or None,
                input=user_input or None, metadata=metadata or None,
            )
        except Exception:
            logger.debug("could not open trace", exc_info=True)

    t = Trace(handle, trace_id)
    try:
        yield t
    except Exception as exc:
        t.update(output=None, level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
        raise


def flush() -> None:
    """Drain buffered spans. Called on shutdown — never in the request path."""
    client = get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.debug("langfuse flush failed", exc_info=True)


def status() -> dict:
    return {
        "enabled": settings.tracing_enabled,
        "host": settings.langfuse_host if settings.tracing_enabled else None,
    }
