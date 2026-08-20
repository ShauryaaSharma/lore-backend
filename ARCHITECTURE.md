# Architecture

This is a **modular monolith** on purpose — no Kafka, no service mesh, no
sharding, in the real ingestion path. It's sized for the traffic Lore
actually sees today, not for hypothetical scale.

## Module map

```
app/
  main.py       FastAPI app factory — lifespan runs migrations on boot, CORS,
                 request-id/latency middleware, mounts health/v1/webhook routers
  config.py     Pydantic-settings Settings — single source of truth for env vars;
                 settings.mode = "live" iff GROQ_API_KEY is set
  logging_setup.py  Structured JSON logging with request_id/tenant contextvars
  metrics.py    In-process Prometheus-format counters/histograms, GET /metrics

  api/          FastAPI routers only — no business logic
    deps.py       API-key extraction, scope resolution, rate limiting
    health.py     GET /health, GET /metrics
    webhook.py    POST /webhook/github — signature verify + delivery dedup + dispatch
    v1/           Versioned API, mounted under /v1 (see API reference in README)

  auth/         API keys, scope resolution, rate limiting
    keys.py        create/resolve/revoke keys, sha256-hashed at rest
    scope.py        resolve_scope() — maps a request to a Canon scope
    ratelimit.py     in-process per-key token-bucket limiter

  ingestion/    GitHub App client, webhook handling, delivery dedup
    github_client.py   JWT -> installation token -> REST, wrapped in retry + circuit breaker
    webhook_handler.py  PR merged -> inscribe; PR opened -> comment; install -> enqueue backfill
    dedup.py             delivery-id dedup backed by Postgres

  retrieval/    "The Canon" — mem0-backed decision memory
    canon.py        core engine: mock (token-overlap) vs live (mem0 + Groq) modes
    rerank.py         cross-encoder reranking of the vector-search shortlist
    summarize.py       bot-noise stripping + PR "understanding" comment generation
    seed_decisions.py   hard-coded seed corpus used by mock mode

  eval/         Golden-set regression harness for /why answer quality
    golden_set.py   hand-written Q&A cases tied to the seed corpus
    harness.py        runs the golden set through answer_why(), scores hit rate

  jobs/         Postgres-backed job queue + worker
    queue.py       SELECT ... FOR UPDATE SKIP LOCKED claim/enqueue/progress/backoff
    worker.py        poll-loop entrypoint: python -m app.jobs.worker
    handlers.py        handle_backfill_installation — the one registered job type

  storage/      Postgres connection pool, migration runner, queries
    db.py           ConnectionPool (psycopg3) + run_migrations()
    queries.py        hand-written SQL for tenants/api_keys/installations/idempotency

  resilience/   Cross-cutting resilience primitives
    retry.py         exponential backoff with full jitter
    circuit_breaker.py  CLOSED -> OPEN -> HALF_OPEN state machine

  examples/     Self-contained demos, isolated from the real app
    kafka_ingestion/  Kafka/Redpanda streaming-ingestion demo — see below
```

## Data flow: GitHub webhook -> Canon

1. GitHub sends a webhook -> `POST /webhook/github` (`app/api/webhook.py`).
2. HMAC-SHA256 signature is verified (`verify_github_signature`; skipped only
   when no secret is configured, for local `curl` testing).
3. The delivery is deduped against a `webhook_deliveries` Postgres table
   (`app/ingestion/dedup.py`) — GitHub retries on any non-2xx, so this stops
   double-inscribing.
4. **`pull_request` events**: opened/reopened -> post a best-effort
   "understanding" comment via Groq; closed & merged ->
   `canon.inscribe_pr(...)` writes the PR discussion into the Canon as a
   decision.
5. **`installation` / `installation_repositories` events**: not processed
   inline. A `backfill_installation` job is enqueued instead, so the webhook
   handler returns within GitHub's ~10s timeout; the worker picks it up
   asynchronously and tracks progress per job row (avoids the classic bug of
   a single in-process progress dict getting corrupted under concurrent
   installs).

## Auth

- Migration `0001_control_plane.sql` creates `tenants`, `api_keys`,
  `installations`, `repos`, `jobs`, `webhook_deliveries`, `idempotency_keys`.
- API keys are sha256-hashed before storage/lookup — never stored or logged
  raw. `create_key()` mints `lk_<token_urlsafe(32)>`, returned exactly once.
- An env-var fallback, `LORE_API_KEYS=key:login,...`, supports zero-DB solo
  self-hosting and is checked before the DB lookup.
- `auth_enabled()` becomes true once *any* key exists (env or DB); every read
  endpoint then requires a valid key and is scoped to that key's tenant only.
  With auth off, scope falls back to `LORE_DEFAULT_ACCOUNT` (single-tenant
  mode).
- Admin operations (`POST` / `DELETE /v1/keys`) are gated by a separate
  `X-Admin-Secret` header (`LORE_ADMIN_SECRET`) — the actual trust boundary
  for minting new tenant credentials, since there's no end-user login yet.
- Rate limiting is an in-process per-key token bucket
  (`RATE_LIMIT_REQUESTS_PER_MINUTE`) — fine for a single backend instance;
  Redis is the noted upgrade path once horizontally scaled.

## Job queue

Postgres-backed, no external broker — deliberately not Celery/RQ/Temporal.
`SELECT ... FOR UPDATE SKIP LOCKED` atomically claims a `queued` job whose
`run_after <= now()` (the same pattern as Oban/GoodJob/River). Job state
(`status`, `attempts`, `progress` jsonb, `error`) lives in the `jobs` table,
so it survives process restarts. Failures requeue with exponential backoff
(`2^attempts` seconds) up to `JOB_MAX_ATTEMPTS`, then fail permanently. The
worker (`app/jobs/worker.py`) is a plain poll loop on
`JOB_POLL_INTERVAL_SECONDS`.

## Resilience

- **Retry** (`app/resilience/retry.py`): exponential backoff with full jitter
  (`sleep = random(0, base * 2**attempt)`, capped at `max_delay`), decorator-
  based, retries on exception type or a custom response predicate (e.g. HTTP
  429/5xx). Wraps every GitHub REST call.
- **Circuit breaker** (`app/resilience/circuit_breaker.py`): CLOSED -> OPEN ->
  HALF_OPEN. Trips after `failure_threshold` consecutive failures, fails fast
  for `cooldown_seconds`, then allows one probe call. One instance per
  downstream dependency — GitHub and Groq each get their own.
- **Idempotency**: `POST /v1/inscribe` honors an `Idempotency-Key` header
  (backed by the `idempotency_keys` table), so a retried CLI call after a
  network blip doesn't double-write a commit.

## Retrieval: reranking + eval

`/why` doesn't just take mem0's top vector-search hits as-is. Dense embedding
similarity is semantically strong but lexically blind — it loses exact-term
matches (a PR number, a ticket ID) to paraphrases that just "sound" closer.
So `answer_why()` widens the shortlist to `RERANK_CANDIDATES` (20) and
rescores it with a fastembed cross-encoder (jointly scores `(query,
candidate)` pairs — too slow to run over the whole Canon, cheap enough over a
shortlist) before keeping the best `RERANK_TOP_K` (6) for the LLM prompt.
Toggle it off with `RERANK_ENABLED=false` to compare directly. Uses the same
ONNX/CPU runtime already pulled in for embeddings, so it adds no new
dependency.

`app/eval/` is a small regression harness: a golden question set (6 hand-
written cases, each tied to a seed-corpus decision with an expected citation
and expected keywords) run through `answer_why()`, scored for
`citation_hit` and `keyword_hit`. It's deterministic in MOCK mode (no API
keys needed), so `tests/test_eval_harness.py` gates CI on a hit-rate floor
(>=0.9). This is a regression gate against retrieval/reranking breakage, not
an exhaustive quality benchmark. Run it manually against the real path with:

```bash
python -m app.eval.harness   # after POST /v1/ingest/seed in LIVE mode
```

## Kafka ingestion demo (not wired in)

`app/examples/kafka_ingestion/` is a self-contained demo of what a streaming
ingestion path would look like *if* Lore ever outgrew the Postgres-polled
queue (e.g. CI events, bulk multi-tenant backfills) — it is **not** part of
the real ingestion path, which remains GitHub webhook -> Postgres job queue.

- `producer.py` publishes a `pr_merged` event (same shape the real webhook
  handler receives) to a Kafka topic.
- `consumer.py`'s `handle_event()` logs the event by default; with `--live`,
  it calls `canon.inscribe_pr(...)` — the *same* function the real webhook
  path calls, showing both ingestion paths converge on the same write.
- Its own `KafkaSettings` and `requirements.txt` are kept separate from
  `app.config.Settings` and the main `requirements.txt`, so running the demo
  never changes real app boot behavior and the module can be deleted without
  touching production code.

```bash
docker compose -f docker-compose.yml -f docker-compose.kafka.yml up -d redpanda
python -m app.examples.kafka_ingestion.consumer
python -m app.examples.kafka_ingestion.producer --sample
```

## Database migrations

No ORM or migration framework — plain numbered `.sql` files in `migrations/`,
applied in order and tracked in a `schema_migrations` table. `run_migrations()`
(`app/storage/db.py`) globs `migrations/*.sql`, applies any not yet recorded,
and commits after each — it's safe to call on every boot, and it is: both
the API (on startup, via lifespan) and the worker call it automatically.
