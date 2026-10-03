# lore-backend

[![PyPI](https://img.shields.io/pypi/v/lore-backend.svg)](https://pypi.org/project/lore-backend/)
[![Python](https://img.shields.io/pypi/pyversions/lore-backend.svg)](https://pypi.org/project/lore-backend/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

The FastAPI service behind [Lore](https://github.com/lorehasit) — an engineering
team's decision memory. Captures the *why* behind merged pull requests (via a
GitHub App) and answers `/why` questions with cited, sourced answers.

A LangGraph agent that can go fetch what it doesn't have, over three memory
tiers and a decision graph, behind a guardrail that won't ship an uncited
answer. Runs entirely on free and self-hosted services.

It also works where the questions come up, inside GitHub:

- **Decision check.** When a PR opens, Lore's comment lists the decisions
  still in force behind the files it changes, with the reasoning for each.
- **`@lore why ...?`** in a PR or issue thread gets an answer in that thread,
  with linked sources.
- **Stale-decision warnings.** A decision nobody formally replaced, but whose
  code has changed a lot since, is flagged as possibly outdated instead of
  being presented as current.

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
| Decision graph | PostgreSQL, recursive CTEs | self-hosted |
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

On top of them sits the **decision graph**: which decisions superseded or
reverted which, and what code each one changed. It is what lets Lore say a
decision is history rather than present it as current. Decisions are
identified as `owner/name#482`, so two repositories' #482s stay separate.
Edges are read from PR text by fixed rules ("Supersedes #12", GitHub's
"Reverts acme/api#12"), never by a model, and each keeps the sentence it
came from as evidence.
Only a revert undoes: if B replaced A and C replaced B, A stays replaced,
but reverting a revert restores the original. Status is walked with a
recursive query on read rather than stored.

The graph powers the **decision check**. When a PR opens, Lore's comment
lists the decisions still in force behind the files it changes (same file
first, then same directory) with the reasoning each was made for, and flags
any the PR says it supersedes or reverts. `/why` only helps someone who
already suspects there is a reason; this reaches the reviewer who does not.
No model in that path. Turn it off with `PR_DECISION_CHECK_ENABLED=false`.

A decision's status only reflects what someone declared, and people rarely
write "Supersedes #12". So the graph also judges **freshness**: a decision
still in force is *possibly outdated* when, after it merged, later PRs that
never mention it deleted one of its files, or changed at least half of them
across at least two PRs. It is an inference, so it is reported next to the
status and never replaces it, and every flag lists the PRs and files behind
it. It shows as a warning in the decision check, makes `/why` hedge rather
than present the decision as current, and is listed at `GET /v1/graph/stale`.

Details in [ARCHITECTURE.md](ARCHITECTURE.md).

## API

| Method & path | Purpose |
|---|---|
| `POST /v1/why` | Core Q&A — returns `answer`, `sources`, `path`, `hops`, `guardrail`, `trace_id` |
| `GET /v1/why/history` | Recently answered questions for this Canon |
| `GET /v1/canon`, `GET /v1/memories` | Cursor-paginated dump of the Canon |
| `POST /v1/lore` | Free-text search, no composed answer |
| `GET /v1/graph/decision?source=acme/api#482` | Is it still in force? What overturned it, its lineage, links, files |
| `GET /v1/graph/files?path=src/auth/` | Decisions that changed a file or directory, newest first, with status |
| `GET /v1/graph/stale` | Decisions still in force that the code has probably moved on from |
| `POST /v1/graph/check` | The PR decision check, for a list of files: from the CLI or a pre-push hook |
| `POST /v1/graph/rebuild` | Re-derive links for decisions ingested before the graph existed |
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
| `PR_DECISION_CHECK_ENABLED` | `true` | List the decisions behind a PR's files in its comment |
| `PR_DECISION_CHECK_LIMIT` | `5` | How many decisions that comment lists |
| `MENTION_TRIGGER` | `@lore` | The handle that asks Lore a question in a thread |
| `MENTION_ALLOWED_ASSOCIATIONS` | `OWNER,MEMBER,COLLABORATOR` | Who can trigger an answer |
| `STALE_MIN_FILE_SHARE` | `0.5` | Share of a decision's files changed since, to flag it |
| `STALE_MIN_LATER_CHANGES` | `2` | Fewest later PRs that must have changed them |

## Upgrading

Migrations run automatically when the API or worker starts.

Migration `0004` renames PR decisions from `PR #482` to `acme/api#482`, so two
repositories' #482s no longer overwrite each other. Postgres is renamed in the
migration itself. The vector store is renamed by the API or worker on its
next start, reusing the stored vectors (no re-embedding); anything that fails
is retried on the start after. Decisions ingested before the graph existed
get their links from `POST /v1/graph/rebuild`.

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
payload shapes handled are in `lore_backend/ingestion/webhook_handler.py`
and `lore_backend/ingestion/mentions.py`.

Subscribe the App to **Pull request**, **Installation** and **Issue
comment** events, with read access to contents and pull requests and write
access to issues (comments and reactions).

### Asking in the thread

Comment `@lore why is this a JWT and not a session?` on a PR or issue and
Lore answers in that thread, with linked sources. The webhook reacts 👀 and
queues the question; the worker answers it through the same agent and
citation guardrail as `/why`, so the background worker must be running.

Only comment authors whose association is in
`MENTION_ALLOWED_ASSOCIATIONS` (default `OWNER,MEMBER,COLLABORATOR`) can
trigger an answer: on a public repository anyone can comment, and each
answer is an LLM run. Bot comments are never answered, so Lore cannot reply
to itself. `MENTION_TRIGGER` changes `@lore` to match your App's name.
