# ADR-0001: Agentic retrieval with LangGraph, tiered memory, and a traced eval gate

**Status:** Accepted — implemented
**Date:** 2026-08-20
**Deciders:** Backend maintainers (@ShauryaaSharma)
**Supersedes:** —

![Proposed v2 architecture](../lore-v2-architecture.png)

## Context

`/why` is currently a fixed retrieval pipeline. Every request runs the same five
steps in the same order (`app/retrieval/canon.py`):

1. Embed the question (fastembed, CPU/ONNX).
2. Pull `RERANK_CANDIDATES` (20) hits from the vector store via mem0.
3. Rescore with a cross-encoder down to `RERANK_TOP_K` (6).
4. Compose an answer with Groq (`llama-3.3-70b-versatile`).
5. Return the answer plus citations.

This works, is cheap, and is deterministic enough that `app/eval/` can gate CI on
it. It has one structural limit that no amount of tuning fixes:

**The pipeline can only answer from what has already been ingested.** When the
Canon does not contain the relevant decision, step 4 still receives six
mediocre hits and still produces a fluent, confident answer. For a product whose
entire value proposition is *citing the real reason a decision was made*, a
confident wrong answer is the worst possible failure mode — worse than "I don't
know."

Three forces push on this now:

- **Retrieval is blind to freshness.** The reranker improves ordering within the
  indexed corpus; it cannot go read a PR that was merged an hour ago and not yet
  backfilled.
- **One vector store is holding three different kinds of memory.** Prompts (how
  to behave), distilled decisions (durable facts), and raw dated events all live
  in the same place and are all retrieved the same way, even though only one of
  them is genuinely a semantic-similarity problem.
- **Answer quality is unobservable in production.** `app/eval/` gates CI against
  a 6-case golden set in MOCK mode. There is no per-request trace, so a
  regression in LIVE mode is diagnosed by guesswork.

**Constraints:**

- Must run on free tiers / self-hosted only. No new recurring cloud spend.
- Must be incrementally shippable. A big-bang rewrite of `app/retrieval/` is not
  acceptable — the current path has to keep working throughout.
- CPU-only. No GPU in the deployment target.
- Small team; maintenance burden is a first-class cost, not a footnote.

## Decision

Move `/why` from a fixed pipeline to an **agentic loop orchestrated by
LangGraph**, backed by **three explicitly separated memory tiers**, and wrapped
in a **trace → eval → gate** loop using self-hosted Langfuse.

Concretely:

1. **Harness.** A LangGraph `StateGraph` per surface (CLI, VS Code, GitHub App).
   Graph state (`messages`, auth scope, surface) is ephemeral per run.
2. **Loop.** The model is given tools instead of a hardcoded retrieval step:
   `search_canon()`, `fetch_pr_diff()`, `search_commits()`, `post_comment()`.
   Most of these wrap clients that already exist in `app/ingestion/` and
   `app/retrieval/`. Capped at **4 hops**; exceeding the cap is a hard failure,
   not a degraded answer.
3. **Guardrail.** Before returning, every claim in the answer must map to a
   decision ID present in the tool results. Unsupported claims fail the run
   rather than shipping as prose.
4. **Memory tiers.**
   - *Procedural* — `prompts/*.md`, git-versioned. Persona, citation rules, tool
     policy. Reviewed in PRs, not edited in a DB.
   - *Semantic* — Qdrant. Durable, distilled decisions. Searched by meaning.
   - *Episodic* — the existing control-plane Postgres. Dated PRs, jobs, past
     `/why` queries. Queried by time and ID with SQL, not by embedding.
   - A **summarizer agent** (Groq `llama-3.1-8b`) periodically distills episodic
     events into semantic facts after N new PRs, bounding vector-store growth.
5. **LLM Ops.** Langfuse (self-hosted, added to `docker-compose.yml`) emits one
   trace per graph run. `app/eval/` becomes the *Eval* stage, extended with an
   LLM-as-judge rubric pass. A **Gate** in CI compares scores to a floor: pass →
   release (git-tagged prompt + RAG config), fail → diagnose against the trace.

## Options considered

### Option A: Keep the pipeline, tune it harder

Better reranking, a larger seed corpus, more aggressive backfill, prompt
iteration.

| Dimension | Assessment |
|---|---|
| Complexity | Low — no new dependencies |
| Cost | $0 |
| Scalability | Fine; latency stays flat and predictable |
| Team familiarity | High — this is the current system |

**Pros:** Zero migration risk. Latency stays a single LLM call. Deterministic,
so the existing MOCK-mode eval keeps working unchanged.

**Cons:** Does not address the actual failure. No amount of reranking lets the
system fetch a decision that was never indexed, and the confident-wrong-answer
mode persists. Treats a structural limit as a tuning problem.

### Option B: Agentic loop on LangGraph *(chosen)*

| Dimension | Assessment |
|---|---|
| Complexity | Medium — one new orchestration dependency, existing logic reused as tools |
| Cost | $0 (MIT license; Groq free tier; Langfuse self-hosted) |
| Scalability | Variable latency (1–4 model calls); free-tier rate limits are the real ceiling |
| Team familiarity | Low today, but LangGraph is the most widely documented option in this space |

**Pros:** Directly fixes the failure mode — the agent can go fetch what it
lacks. Graph structure makes the hop cap, checkpointing, and tracing hooks
first-class rather than hand-rolled. Migration is additive: `search_canon` is
the current retrieval function with a tool decorator on it, so the old path
survives as a fallback and both can be scored on the same golden set.

**Cons:** Non-deterministic — the same question can take a different number of
hops, which complicates the MOCK-mode eval. Latency rises for multi-hop
questions. Adds a framework whose abstractions must be understood to debug.

### Option C: Hand-rolled tool loop (no framework)

A plain `while` loop over Groq's tool-calling API.

| Dimension | Assessment |
|---|---|
| Complexity | Low to start, grows steadily |
| Cost | $0 |
| Scalability | Same as Option B |
| Team familiarity | High — it's just Python |

**Pros:** No framework abstraction between us and the model. Fully debuggable.
Matches the codebase's existing "no ORM, hand-written SQL" instinct.

**Cons:** Hop capping, checkpointing, retry-on-tool-failure, streaming, and
trace instrumentation all get reimplemented by hand — this is roughly what
LangGraph is. The existing preference for hand-rolling is defensible for SQL
(a stable, well-understood target) and much less so for agent orchestration,
which is still moving quickly.

### Option D: LangChain `AgentExecutor`

**Rejected.** It is the higher-level, less explicit sibling of Option B — the
control flow is inside the executor rather than a graph you can read. For a
system that needs a hard hop cap and per-node tracing, the graph is the point.

### Sub-decision: drop mem0 from the retrieval path

**Agreed 2026-08-20.** mem0 currently wraps LLM + embedder + vector store and
manages memory consolidation. Under this ADR it is **removed**, with
`search_canon` calling fastembed + Qdrant directly.

**Rationale:** mem0's real value-add is automatic fact extraction and
insert-vs-update logic — precisely the job moving to the explicit summarizer
agent. Keeping both means two systems consolidating memory with different
opinions and neither owning the result. Separately, the tool needs raw scored
hits with decision IDs so the cross-encoder and the citation guardrail can do
their jobs, which means reaching around mem0's managed `search()` anyway. And
since episodic retrieval is SQL regardless, mem0 would only ever cover half the
retrieval path.

**Cost of this:** we take on dedup and fact-extraction maintenance ourselves.

**Fallback if that cost bites:** keep mem0 as the store behind `search_canon`
but disable its automatic consolidation, letting the summarizer be the only
writer. This preserves the tiering without owning the extraction logic.

## Trade-off analysis

The central trade is **determinism for correctness-honesty**. The current
pipeline always answers; the proposed loop sometimes takes longer and sometimes
refuses. For a decision-memory product, a system that can say "the Canon does
not have this, here is the PR diff I found instead" is more valuable than one
that always produces fluent prose. We are deliberately buying variable latency
and a harder eval story in exchange for the ability to be right.

The second trade is **framework dependency for orchestration correctness**
(Option B vs C). This cuts against the codebase's stated preference for
hand-written primitives — no ORM, hand-rolled retry and circuit breaker, a
Postgres job queue instead of Celery. Those choices were right because the
problems are stable and well-understood. Agent orchestration is neither, and
the hop cap, checkpointing, and trace instrumentation we would hand-roll are
exactly what the framework provides. We accept the dependency here and keep the
hand-rolled instinct everywhere else.

The third trade is **maintenance for control** (the mem0 sub-decision). Taking
ownership of consolidation is real work. It is justified because citation
correctness is the product, and correctness we cannot inspect is not something
we can promise.

## Consequences

**Easier:**

- Questions about very recent PRs get real answers instead of confident guesses.
- Diagnosing a bad answer becomes reading a trace instead of guessing at a step.
- Prompt changes become reviewable, git-tagged releases with a measured
  before/after rather than silent string edits.
- Episodic queries ("what did we decide last month?") stop being forced through
  semantic search.

**Harder:**

- Eval must handle non-determinism — variable hop counts break exact-match
  assertions; the golden set needs to assert on outcomes, not paths.
- `/why` p95 latency rises for multi-hop questions.
- Groq free-tier rate limits now bind on hops-per-question, not
  questions-per-minute. Worth measuring before the loop is enabled by default.
- One more service (Langfuse) in the compose file, and its Postgres.
- We own memory consolidation.

**To revisit:**

- Whether the 4-hop cap is right — instrument first, tune from traces.
- Whether the LLM-as-judge scores correlate with human judgment enough to gate
  CI on, or whether it should start as observe-only.
- Whether procedural memory in flat files scales past a handful of prompts.
- The mem0 fallback above, if consolidation maintenance proves costly.

## Action items

1. [x] Add Langfuse as a compose overlay and instrument the request path
       (`app/obs/tracing.py`, `docker-compose.langfuse.yml`).
2. [x] Put the agent behind `AGENT_LOOP_ENABLED`, with the v1 pipeline still
       reachable as the comparison baseline.
3. [x] Implement `search_canon` / `recent_decisions` / `fetch_pr_diff` /
       `search_commits` as tools over the existing Canon and GitHub clients
       (`app/agent/tools.py`).
4. [x] Enable multi-hop with the 4-hop cap enforced in the router;
       `python -m app.eval.harness --compare` scores both paths on the same
       store.
5. [x] Split memory tiers: `prompts/*.md`, the episodic SQL retriever
       (`migrations/0002_memory_layer.sql`), and the summarizer on the
       existing job queue.
6. [x] Add the LLM-as-judge eval stage, observe-only (`JUDGE_ENABLED=false`).
7. [x] Remove mem0.
8. [ ] Run the judge observe-only for two weeks, then decide whether it earns
       a place in `gate()`.
9. [ ] Measure real hop distribution from traces before trusting `4` as the
       right cap.
10. [ ] Write follow-up ADRs for the guardrail's failure semantics and the
        summarizer's consolidation policy.

## Implementation notes

Two things landed differently from the plan above, both deliberate:

**Ingestion writes through to both stores.** The plan implied events land in
episodic memory and reach semantic memory only via consolidation. That would
mean a PR merged sixty seconds ago is unanswerable until the next batch runs
— a worse product for a marginal storage saving. Ingestion now writes both;
the summarizer distils and overwrites in place afterwards.

**The guardrail applies to both paths.** It was conceived as part of the
agent loop. An uncited answer is no more shippable because the v1 pipeline
produced it, so `_answer_pipeline` runs the same check.

## Notes

This decision was made in a design conversation, not a pull request — which
means Lore's own ingestion path would never have captured it. Worth considering
whether design discussions deserve an ingestion path alongside merged PRs.
