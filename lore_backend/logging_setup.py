"""Structured JSON logging with a request-id (and tenant/repo when known) on
every line, so a slow or failing `/v1/why` call is traceable without a full
tracing stack — appropriate for a single-process backend at this scale."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid

from lore_backend.config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
tenant_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "tenant": tenant_var.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_json else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
