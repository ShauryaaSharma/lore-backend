# lore-backend

The FastAPI service behind [Lore](https://github.com/lorehasit) — an engineering
team's decision memory. Captures the *why* behind merged pull requests (via a
GitHub App) and answers `/why` questions with cited, sourced answers.

Companion repos: [`lore-cli`](https://github.com/lorehasit/lore-cli) (the
`npx lore` git-hook CLI) and
[`lore-vscode-extension`](https://github.com/lorehasit/lore-vscode-extension).

## Quickstart (self-host)

```bash
cp .env.example .env   # works as-is in MOCK mode — no keys required
docker compose up
curl localhost:8000/health
```

That's Postgres + the API + the background worker, all in one command. Add
`GROQ_API_KEY` to `.env` and restart to go LIVE (real retrieval, real GitHub
ingestion).

## Architecture

```
app/
  api/        FastAPI routers only (v1/*, webhook, health) — no business logic
  auth/       API keys (hashed, DB-backed + env fallback), scope resolution, rate limiting
  ingestion/  GitHub App client (retry/circuit-breaker wrapped), webhook handling, delivery dedup
  retrieval/  The Canon — mem0-backed decision memory, PR summarization
  jobs/       Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED) + worker
  storage/    Postgres connection pool, migration runner, hand-written queries
  resilience/ Retry with backoff+jitter, circuit breaker
```

Modular monolith on purpose — see the project's architecture notes for what's
deliberately *not* here yet (no Kafka, no service mesh, no sharding): this is
sized for the traffic Lore actually sees today, not for hypothetical scale.
(`app/examples/kafka_ingestion/` is a self-contained demo of what a streaming
ingestion path would look like *if* that changed — isolated from the real
app, not wired in.)

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

## Deploying the GitHub App

See the webhook payload shapes handled in `app/ingestion/webhook_handler.py`.
Point the App's webhook URL at `<your-host>/webhook/github` and set
`GITHUB_WEBHOOK_SECRET` / `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY`.
