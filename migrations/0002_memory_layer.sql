-- Episodic memory: dated events and past answers.
--
-- This is the half of retrieval that vector search is wrong for. "What did we
-- decide last month?" is an ORDER BY on a timestamp, not a nearest-neighbour
-- lookup, and forcing it through embeddings gives you decisions that *sound*
-- recent. Semantic memory (Qdrant/pgvector) keeps the distilled facts;
-- this keeps the raw, dated record they were distilled from.

create table if not exists decision_events (
    id              bigserial primary key,
    scope           text        not null,
    kind            text        not null,          -- pr | commit | seed
    source          text        not null,          -- "PR #482", "commit a1b2c3d"
    title           text        not null default '',
    body            text        not null default '',
    author          text        not null default '',
    repo            text        not null default '',
    url             text        not null default '',
    occurred_at     timestamptz,                   -- merged/committed date, not ingest time
    consolidated_at timestamptz,                   -- null = not yet distilled into semantic memory
    created_at      timestamptz not null default now(),
    unique (scope, source)
);

create index if not exists decision_events_scope_time_idx
    on decision_events (scope, occurred_at desc nulls last);

-- Partial index: the consolidation job only ever asks for the unconsolidated
-- tail, which stays small even as the table grows.
create index if not exists decision_events_pending_idx
    on decision_events (scope, id) where consolidated_at is null;

-- Past /why runs. Feeds "have we asked this before?", and gives the ops layer
-- something to join traces against without depending on Langfuse retention.
create table if not exists why_queries (
    id          bigserial primary key,
    scope       text        not null,
    question    text        not null,
    answer      text        not null default '',
    sources     jsonb       not null default '[]'::jsonb,
    hops        int         not null default 0,
    latency_ms  int         not null default 0,
    trace_id    text,
    path        text        not null default 'agent',  -- agent | pipeline | mock
    created_at  timestamptz not null default now()
);

create index if not exists why_queries_scope_time_idx
    on why_queries (scope, created_at desc);
