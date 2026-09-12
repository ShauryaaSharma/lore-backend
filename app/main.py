"""Lore backend — FastAPI service the VS Code extension, CLI, and future
surfaces call.

Run (dev):
    uvicorn app.main:app --reload --port 8000

Run the background worker separately (see docker-compose.yml):
    python -m app.jobs.worker

Works with zero LLM keys (mock mode). Add GROQ_API_KEY to .env to go live.
Always requires DATABASE_URL — the control plane (auth, jobs, webhook
dedup) lives in Postgres regardless of which vector store backs the Canon.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import router as v1_router
from app.api.webhook import router as webhook_router
from app.logging_setup import configure_logging, new_request_id, request_id_var
from app.metrics import incr, observe
from app.storage.db import run_migrations

configure_logging()
logger = logging.getLogger("lore.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    applied = run_migrations()
    if applied:
        logger.info("applied migrations: %s", applied)
    yield


app = FastAPI(title="Lore", version="1.0.0", lifespan=lifespan)

# VS Code webviews call from an opaque origin; allow all for local dev. A
# hosted deployment can tighten this via a reverse proxy if needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    token = request_id_var.set(new_request_id())
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        observe("http_request_seconds", time.perf_counter() - t0)
        incr(f"http_requests_total{{path={request.url.path}}}")
        request_id_var.reset(token)
    return response


app.include_router(health_router)
app.include_router(v1_router)
app.include_router(webhook_router)
