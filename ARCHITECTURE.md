# Architecture

Lore answers `/why` with cited, sourced answers about a team's own
engineering decisions. The system is shaped by one constraint: **an
uncited answer is worse than no answer.** Everything below follows from
that.

Implemented per [ADR-0001](docs/adr/0001-agentic-retrieval-with-langgraph.md).

![v2 architecture](docs/lore-v2-architecture.png)

## The four regions

| Region | What it is | Where |
|---|---|---|
| **Harness** | A LangGraph `StateGraph`, one compiled graph per run | `lore_backend/agent/` |
| **Loop** | The model with tools, capped at 4 hops | `lore_backend/agent/tools.py` |
| **Memory** | Three tiers: procedural, semantic, episodic | `lore_backend/memory/` |
| **LLM Ops** | Trace → observe → eval → gate | `lore_backend/obs/`, `lore_backend/eval/` |

## Module map

```
lore_backend/
  main.py       FastAPI app factory — migrations on boot, CORS, request-id
                 middleware, trace flush on shutdown
  config.py     Pydantic-settings Settings — one source of truth, fails fast

  agent/        The harness (v2)
    graph.py      StateGraph: agent -> tools -> agent -> guardrail -> END
    tools.py       search_canon, recent_decisions, fetch_pr_diff,
                    search_commits, post_comment — built per request
    guardrail.py    citation verification; rejects ungrounded answers
    state.py         GraphState — ephemeral, reducer-annotated

  memory/       The memory layer
    procedural.py   prompts/*.md loader, mtime-cached
    semantic.py      Qdrant or pgvector, called direct (no mem0)
    episodic.py       Postgres — decision_events, why_queries
    consolidate.py     summarizer agent: episodic -> semantic

  obs/          LLM Ops
    tracing.py      Langfuse behind a null object; never raises, never blocks

  eval/         The gate
    golden_set.py   hand-written Q&A cases tied to the seed corpus
    harness.py       scores the active path; --compare runs both
    judge.py          LLM-as-judge against prompts/judge.md (observe-only)

  api/          FastAPI routers only — no business logic
  auth/         API keys (hashed, DB-backed + env fallback), scope, rate limit
  ingestion/    GitHub App client, webhook handling, delivery dedup
  retrieval/    canon.py (dispatch + writes), rerank.py, summarize.py
  jobs/         Postgres queue (FOR UPDATE SKIP LOCKED) + worker
  storage/      connection pool, migration runner, hand-written SQL
  resilience/   retry with backoff+jitter, circuit breaker
  examples/     self-contained demos, isolated from the real app

prompts/        Procedural memory — persona, citation policy, tool policy,
                 judge rubric. Git-versioned, reviewed in PRs.
```

## The loop

```
START → agent ─┬─(tool calls, hops left)→ tools → agent
               └─(answer, or out of hops)→ guardrail → END
```

v1 was a fixed pipeline: embed, search, rerank, prompt, return. It could
only ever answer from what had already been indexed — and when the Canon
lacked a decision, it still produced a fluent, confident, wrong answer.

The loop fixes the structural half. The model gets tools and decides whether
it has enough to answer or needs to go fetch:

| Tool | When the model should reach for it |
|---|---|
| `search_canon` | Always first — recorded decisions, by meaning |
| `recent_decisions` | "Lately", "last month" — similarity can't order by time |
| `fetch_pr_diff` | The question names a PR the Canon has no decision for |
| `search_commits` | A reason recorded as a `Why:` trailer, never in a PR |
| `post_comment` | Only when explicitly asked; the one outward side effect |

Two properties are enforced in code rather than asked for in the prompt:

- **Scope is bound, not passed.** Tools close over the scope resolved from
  the caller's API key, so the model has no way to name a tenant. Tools are
  built per request for this reason (`lore_backend/agent/tools.py`).
- **The hop cap terminates the loop.** At `AGENT_MAX_HOPS` the router sends
  the run to the guardrail regardless of what the model wants. A runaway
  loop fails loud instead of burning the Groq quota.

## The guardrail

Where an answer becomes shippable, or doesn't. It checks the answer against
what retrieval *actually returned* — not against what the answer claims.

| Verdict | Meaning |
|---|---|
| `ok` | Every citation maps to a retrieved decision |
| `abstain` | Says the Canon has no record — correct behaviour, not a failure |
| `violation` | Cites something never retrieved, or states specifics with no citation |

A violation never reaches the user. It's replaced with an honest message
naming the closest records found.

It's deliberately string matching, not an LLM check: a guardrail that can
hallucinate is not a guardrail. Both paths run it — an uncited answer isn't
more shippable because the v1 pipeline produced it.

## The memory layer

One undifferentiated vector store conflated three things that want different
storage and answer different questions.

**Procedural** — *how to behave.* `prompts/*.md`, git-versioned. A prompt in
a database is a config change nobody can review; as a file, changing the
persona or the citation rules is a diff in a PR. Cached by mtime, so edits
land without a restart in development.

**Semantic** — *durable facts.* Qdrant (or pgvector), searched by meaning,
called directly. mem0 used to wrap this; it came out because the agent needs
the raw score, the stable decision id and untouched metadata — the reranker,
the guardrail and provenance each need one of those — and because
consolidation is now an explicit job rather than a framework's side effect.

**Episodic** — *dated events.* Postgres (`decision_events`, `why_queries`).
"What did we decide last month" is `order by occurred_at desc`, not
nearest-neighbour; running it through embeddings returns decisions that
*sound* recent, which is subtly wrong rather than merely slow. The
control-plane database was already holding most of this — this gives it a
retrieval path instead of leaving it write-only.

### Write-through, then compact

Ingestion writes to episodic *and* semantic memory at once, so a PR merged
sixty seconds ago is answerable now. The summarizer agent
(`SUMMARIZER_MODEL`, Llama 3.1 8B) later distils the raw text and marks the
event consolidated — same `source`, so the distilled version overwrites the
raw one instead of competing with it in search.

Compaction runs on the worker: the sweep looks for tenants with
`CONSOLIDATE_AFTER_N_EVENTS` pending and queues a job each. A failed
summary leaves its event pending, so nothing is silently dropped.

## LLM Ops

**Trace** — one Langfuse trace per graph run: every tool call, every hop, the
guardrail verdict, the prompt fingerprint. `trace_id` is stored on the
`why_queries` row, so a bad answer in the database opens as a trace in the
UI.

Two rules hold throughout `lore_backend/obs/`: tracing never raises into the caller,
and never blocks the answer (spans flush at shutdown). Unconfigured, the
whole layer is a null object.

**Eval** — the golden set, plus an LLM-as-judge pass scoring *grounded*,
*answers_question*, and *explains_why* against `prompts/judge.md`.

**Gate** — `hit_rate` and `citation_accuracy` against configured floors.
The judge is **observe-only** (`JUDGE_ENABLED=false`): a judge that hasn't
been checked against human reading is a metric, not a policy, and gating on
it early means optimising for a model's taste.

```bash
python -m lore_backend.eval.harness --compare
```

Scores the v1 pipeline and the v2 agent back to back on the same store —
which is the point of keeping the fallback: the loop has to out-perform
something. Note the agent path is non-deterministic; one run is a sample,
not a measurement.

## Job queue

Postgres-backed, no broker — `SELECT ... FOR UPDATE SKIP LOCKED` to claim a
due job (the Oban/GoodJob/River pattern). Job state lives in the `jobs`
table, so it survives restarts; failures requeue with exponential backoff up
to `JOB_MAX_ATTEMPTS`. Two job types: `backfill_installation` and
`consolidate_memory`.

## Ingestion

1. GitHub webhook → `POST /webhook/github`.
2. HMAC-SHA256 signature verified.
3. Delivery deduped against `webhook_deliveries` — GitHub retries on any
   non-2xx, so this stops double-inscribing.
4. **PR merged** → `canon.inscribe_pr` writes to episodic + semantic memory.
   **PR opened** → best-effort "understanding" comment.
5. **Installation events** → enqueue a backfill job so the webhook returns
   inside GitHub's ~10s timeout; the worker tracks progress per job row.

## Resilience

- **Retry** — exponential backoff with full jitter, wrapping every GitHub
  REST call.
- **Circuit breaker** — CLOSED → OPEN → HALF_OPEN, one instance per
  downstream dependency (GitHub and Groq each get their own).
- **Idempotency** — `POST /v1/inscribe` honours `Idempotency-Key`, so a
  retried CLI call after a network blip doesn't double-write.
- **Degradation** — a vector-store outage returns "no record" rather than a
  500; a failing tool is reported to the model as text so it can try another
  angle.

## Migrations

Plain numbered `.sql` files in `migrations/`, applied in order and tracked in
`schema_migrations`. No ORM. `run_migrations()` is safe on every boot and is
called by both the API and the worker.

- `0001_control_plane.sql` — tenants, api_keys, installations, repos, jobs,
  webhook_deliveries, idempotency_keys
- `0002_memory_layer.sql` — decision_events, why_queries

The pgvector table is created lazily at first use rather than in a migration,
so a plain Postgres without the extension can still run the control plane.

## What's deliberately not here

A modular monolith on purpose — no Kafka, no service mesh, no sharding in the
real ingestion path. `lore_backend/examples/kafka_ingestion/` is a self-contained demo
of what a streaming path *would* look like, isolated so it can be deleted
without touching production code.
