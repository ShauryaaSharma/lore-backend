# lore-backend

[![PyPI](https://img.shields.io/pypi/v/lore-backend.svg)](https://pypi.org/project/lore-backend/)
[![Python](https://img.shields.io/pypi/pyversions/lore-backend.svg)](https://pypi.org/project/lore-backend/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

The FastAPI service behind [Lore](https://github.com/lorehasit) — an engineering
team's decision memory. Captures the *why* behind merged pull requests (via a
GitHub App) and answers `/why` questions with cited, sourced answers.

A LangGraph agent that can go fetch what it doesn't have, over three memory
tiers, behind a guardrail that won't ship an uncited answer. Runs entirely on
free and self-hosted services.

Companion repos: [`lore-cli`](https://github.com/lorehasit/lore-cli) (the
`npx lore` git-hook CLI that captures commit `Why:` trailers) and
[`lore-vscode-extension`](https://github.com/lorehasit/lore-vscode-extension).

For the design and the reasoning behind it, see
[ARCHITECTURE.md](ARCHITECTURE.md) and
[ADR-0001](docs/adr/0001-agentic-retrieval-with-langgraph.md).

![v2 architecture](docs/lore-v2-architecture.png)

## Quickstart (self-host)

```bash
cp .env.example .env   # works as-is in MOCK mode — no keys required
docker compose up
curl localhost:8000/health
```

Postgres, Qdrant, the API and the worker, in one command.

- **MOCK mode** (no `GROQ_API_KEY`): answers come from token-overlap search
  over a curated seed corpus. Deterministic, no external calls — good for
  demos and CI.
- **LIVE mode**: add `GROQ_API_KEY` and restart for the agent loop, real
  retrieval, and real GitHub ingestion.

`DATABASE_URL` is required in both modes — the control plane and episodic
memory live in Postgres regardless.

## Install from PyPI

Published at [pypi.org/project/lore-backend](https://pypi.org/project/lore-backend/).

`docker compose up` stays the recommended way to run Lore — it brings its own
Postgres and Qdrant. The package is for embedding the service in an existing
deployment, or importing the memory layer directly:

```bash
pip install lore-backend
export DATABASE_URL=postgresql://lore:lore@localhost:5432/lore
lore-backend                 # the API server (--host/--port/--reload)
lore-backend-worker          # the background job worker
```

Both scripts read the same environment as the Docker stack (see
[.env.example](.env.example)); you supply Postgres and Qdrant yourself.
Prompts and migrations ship inside the package, so procedural memory and the
migration runner work from an install with no checkout.

## Tech stack

| Layer | Choice | Cost |
|---|---|---|
| Web framework | FastAPI + Uvicorn | — |
| Orchestration | **LangGraph** `StateGraph` | OSS, MIT |
| Agent LLM | Groq — Llama 3.3 70B | free tier |
| Summarizer LLM | Groq — Llama 3.1 8B | free tier |
| Embeddings + reranking | fastembed (ONNX, CPU) | $0, no API |
| Semantic memory | Qdrant (or pgvector) | free / self-host |
| Episodic memory + control plane | PostgreSQL | self-hosted |
| Job queue | Postgres `FOR UPDATE SKIP LOCKED` | no broker |
| Tracing + eval | Langfuse | OSS, self-host |
| Auth | DB-backed API keys, sha256-hashed | — |
| Testing | pytest, ruff | — |

No new cloud bill. Nothing here requires an account anywhere.

## How an answer gets made

```
question → agent ─┬─(needs more)→ tools → agent
                  └─(has enough)→ guardrail → answer + citations
```

The model decides whether the Canon covered the question or whether it needs
to go read the PR itself. Capped at 4 hops. Before anything reaches the user,
the guardrail checks every citation against what retrieval actually returned —
an answer citing a PR that was never retrieved does not ship.

Memory is three tiers, because they answer different questions:
**procedural** (how to behave — `prompts/*.md`, git-versioned),
**semantic** (durable distilled decisions — vector search), and
**episodic** (dated events and past answers — SQL, ordered by time).

Details in [ARCHITECTURE.md](ARCHITECTURE.md).

## API

| Method & path | Purpose |
|---|---|
| `POST /v1/why` | Core Q&A — returns `answer`, `sources`, `path`, `hops`, `guardrail`, `trace_id` |
| `GET /v1/why/history` | Recently answered questions for this Canon |
| `GET /v1/canon`, `GET /v1/memories` | Cursor-paginated dump of the Canon |
| `POST /v1/lore` | Free-text search, no composed answer |
| `POST /v1/ingest/seed` | Load the seed corpus (LIVE mode) |
| `POST /v1/inscribe` | CLI writes a commit's `Why:` (idempotent) |
| `GET /v1/backfill/status`, `POST /v1/backfill/run` | Installation backfill |
| `POST /v1/keys`, `DELETE /v1/keys/{id}` | API keys (admin-secret-gated) |
| `GET /health` | Mode, active path, loaded prompts, tracing status |
| `GET /metrics` | Prometheus-format counters |
| `POST /webhook/github` | GitHub App webhook receiver |

## Eval

```bash
python -m lore_backend.eval.harness              # score the active path
python -m lore_backend.eval.harness --compare    # v1 pipeline vs v2 agent, same store
python -m lore_backend.eval.harness --judge      # add LLM-as-judge (LIVE only)
```

A golden question set scored for citation accuracy and relevance.
Deterministic in MOCK mode, so `tests/test_eval_harness.py` holds a hit-rate
floor as part of `pytest`, and the harness itself exits non-zero when the
gate fails — run it before merging anything that touches retrieval. The LLM
judge is observe-only until its scores have been checked against human
reading.

The `--compare` mode is why the v1 pipeline is still in the tree: the loop
has to out-perform something. Note that the agent path is non-deterministic —
one run is a sample, not a measurement.

## Tracing (optional)

```bash
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up
```

Open http://localhost:3000, create a project, put its keys in `.env` as
`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`, restart the backend. Until
then every trace call is a no-op — nothing in the request path depends on
Langfuse being reachable.

## Configuration

Everything lives in `.env.example` with safe defaults. The knobs worth
knowing:

| Variable | Default | What it does |
|---|---|---|
| `AGENT_LOOP_ENABLED` | `true` | `false` falls back to the v1 pipeline |
| `AGENT_MAX_HOPS` | `4` | Tool-call budget per question |
| `RERANK_ENABLED` | `true` | Cross-encoder rescoring of the shortlist |
| `VECTOR_STORE` | `qdrant` | Or `pgvector` to reuse the same Postgres |
| `CONSOLIDATE_AFTER_N_EVENTS` | `25` | When the summarizer distils a tenant's backlog |
| `JUDGE_ENABLED` | `false` | LLM-as-judge in the eval report |
| `EVAL_HIT_RATE_FLOOR` | `0.9` | What the eval gate enforces |

## Local dev (no Docker)

```bash
python -m venv .venv && . .venv/Scripts/activate  # or source .venv/bin/activate
pip install -r requirements.txt
# Needs a reachable Postgres — `docker compose up postgres` or your own.
uvicorn lore_backend.main:app --reload --port 8000
# in another terminal:
python -m lore_backend.jobs.worker
```

## Testing

```bash
pytest
ruff check .
```

Tests need a live Postgres (`DATABASE_URL`) — they run real migrations and
truncate between cases rather than mocking the database. The agent, judge and
summarizer are driven by scripted fakes, so the suite makes no network calls
and needs no API keys.

`tests/test_kafka_ingestion_demo.py` needs the demo's own optional
dependency (`lore_backend/examples/kafka_ingestion/requirements.txt`).

## Deploying the GitHub App

Point the App's webhook URL at `<your-host>/webhook/github` and set
`GITHUB_WEBHOOK_SECRET` / `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY`. The
payload shapes handled are in `lore_backend/ingestion/webhook_handler.py`.
