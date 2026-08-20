# lore-backend

The FastAPI service behind [Lore](https://github.com/lorehasit) — an engineering
team's decision memory. Captures the *why* behind merged pull requests (via a
GitHub App) and answers `/why` questions with cited, sourced answers.

Companion repos: [`lore-cli`](https://github.com/lorehasit/lore-cli) (the
`npx lore` git-hook CLI that captures commit `Why:` trailers) and
[`lore-vscode-extension`](https://github.com/lorehasit/lore-vscode-extension).

For a detailed look at the module map, data flow, auth, job queue,
resilience patterns, and retrieval/reranking design, see
[ARCHITECTURE.md](ARCHITECTURE.md).

## Quickstart (self-host)

```bash
cp .env.example .env   # works as-is in MOCK mode — no keys required
docker compose up
curl localhost:8000/health
```

That's Postgres + the API + the background worker, all in one command.

- **MOCK mode** (no `GROQ_API_KEY`): `/why` answers come from token-overlap
  search over a hard-coded seed corpus. Good for demos and CI — deterministic,
  zero external calls.
- **LIVE mode**: add `GROQ_API_KEY` to `.env` and restart for real retrieval
  (mem0 + embeddings + reranking) and real GitHub ingestion.

`DATABASE_URL` (Postgres) is required in both modes — the control plane
(auth, jobs, webhook dedup) always lives there.

## Tech stack

| Concern | Choice | Notes |
|---|---|---|
| Web framework | FastAPI + Uvicorn (ASGI) | `app/main.py` |
| Config | `pydantic-settings` | single `Settings` object, fail-fast validation |
| Database | PostgreSQL (`pgvector/pgvector:pg16` image) | control plane always; optional vector store too |
| DB driver | `psycopg` v3 + `psycopg-pool` | no ORM — hand-written SQL |
| Job queue | Postgres (`FOR UPDATE SKIP LOCKED`) | no Celery/RQ/Redis — see [ARCHITECTURE.md](ARCHITECTURE.md#job-queue) |
| Auth | DB-backed API keys (sha256-hashed) + env fallback | see [ARCHITECTURE.md](ARCHITECTURE.md#auth) |
| GitHub integration | GitHub App, `PyJWT[crypto]` (RS256) | JWT → installation token → REST |
| LLM | Groq (`groq` SDK), default `llama-3.3-70b-versatile` | only in LIVE mode |
| Memory / RAG | `mem0ai` | wraps LLM + embedder + vector store |
| Embeddings | `fastembed` (ONNX, CPU), default `thenlper/gte-large` | no GPU required |
| Reranking | `fastembed` cross-encoder, default `Xenova/ms-marco-MiniLM-L-6-v2` | see [ARCHITECTURE.md](ARCHITECTURE.md#retrieval-reranking--eval) |
| Vector store | `qdrant` (local file, default) or `pgvector` (same Postgres) | `VECTOR_STORE` env |
| Resilience | Custom retry-with-jitter + circuit breaker | `app/resilience/` |
| Observability | Structured JSON logs, in-process Prometheus-format metrics | `GET /metrics` |
| Testing | `pytest`, `ruff` | needs a live Postgres |
| Packaging | Single `python:3.12-slim` Docker image | same image for API and worker |

## API reference

Versioned routes are mounted under `/v1`; system routes are not versioned.

| Method & path | Purpose |
|---|---|
| `GET /health` | Mode (mock/live), auth status, GitHub App status |
| `GET /metrics` | Prometheus-format counters/histograms |
| `POST /webhook/github` | GitHub App webhook receiver |
| `POST /v1/why` | Core Q&A — `answer_why(question, scope)` |
| `GET /v1/canon`, `GET /v1/memories` | Cursor-paginated dump of the Canon |
| `POST /v1/lore` | Free-text search over the Canon (no narrative answer) |
| `POST /v1/ingest/seed` | Load the seed corpus into mem0 (LIVE mode) |
| `POST /v1/inscribe` | CLI "Scribe" writes a commit's `Why:` (idempotent) |
| `GET /v1/backfill/status` | Query installation backfill job status |
| `POST /v1/backfill/run` | Manually trigger an installation backfill |
| `POST /v1/keys` | Issue an API key (admin-secret-gated) |
| `DELETE /v1/keys/{id}` | Revoke an API key (admin-secret-gated) |

## Configuration

All variables live in `.env.example` (safe defaults, no real secrets — the
file works as-is in MOCK mode).

| Category | Variables |
|---|---|
| Control plane (always required) | `DATABASE_URL` |
| LLM (Groq) | `GROQ_API_KEY`, `GROQ_MODEL` |
| Embeddings (local, fastembed) | `EMBEDDER_MODEL`, `EMBEDDER_DIMS` |
| Reranking (local, fastembed) | `RERANK_ENABLED`, `RERANK_MODEL`, `RERANK_CANDIDATES`, `RERANK_TOP_K` |
| Canon vector storage | `VECTOR_STORE` (`qdrant` or `pgvector`) |
| GitHub personal-token ingestion | `GITHUB_TOKEN` |
| GitHub App webhook | `GITHUB_WEBHOOK_SECRET` |
| GitHub App identity | `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_PRIVATE_KEY_PATH`, `BACKFILL_DAYS` |
| Retrieval scope (single-tenant) | `LORE_DEFAULT_ACCOUNT` |
| Multi-tenant auth env fallback | `LORE_API_KEYS` (comma-separated `key:login` pairs) |
| Admin | `LORE_ADMIN_SECRET` |
| Jobs/worker | `JOB_POLL_INTERVAL_SECONDS`, `JOB_MAX_ATTEMPTS` |
| Rate limiting | `RATE_LIMIT_REQUESTS_PER_MINUTE` |
| Observability | `LOG_LEVEL`, `LOG_JSON` |

## Local dev (no Docker)

```bash
python -m venv .venv && . .venv/Scripts/activate  # or source .venv/bin/activate
pip install -r requirements.txt
# Needs a reachable Postgres — either `docker compose up postgres` or your own.
uvicorn app.main:app --reload --port 8000
# in another terminal:
python -m app.jobs.worker
```

## Testing

```bash
pytest
ruff check .
```

Tests need a live, reachable Postgres (`DATABASE_URL`) — they run real
migrations and truncate control-plane tables between tests rather than
mocking the database. Notable suites: `test_jobs_queue.py` (claim semantics,
backoff, independent per-installation progress), `test_auth.py`,
`test_idempotency.py`, `test_webhook_dedup.py`, `test_resilience.py`
(retry/circuit-breaker), `test_rerank.py` and `test_eval_harness.py`
(retrieval quality, CI regression gate), `test_kafka_ingestion_demo.py`
(fully mocked, no real broker).

## Deploying the GitHub App

See the webhook payload shapes handled in `app/ingestion/webhook_handler.py`.
Point the App's webhook URL at `<your-host>/webhook/github` and set
`GITHUB_WEBHOOK_SECRET` / `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY`.
