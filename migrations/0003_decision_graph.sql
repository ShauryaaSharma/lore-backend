-- Decision graph: how decisions relate to each other and to the code.
--
-- Nodes are the rows of decision_events, keyed by (scope, source). Edges are
-- kept separately rather than as foreign keys because they routinely point
-- at decisions Lore has not ingested yet: a PR that says "supersedes #12"
-- is a real fact even when #12 predates the backfill window. Those edges
-- are stored and reported as unresolved, and start counting the moment the
-- target is ingested.

create table if not exists decision_links (
    scope        text        not null,
    from_source  text        not null,
    to_source    text        not null,
    -- supersedes / reverts overturn the target; references only mentions it.
    kind         text        not null check (kind in ('supersedes', 'reverts', 'references')),
    evidence     text        not null default '',   -- the sentence the edge was read from
    created_at   timestamptz not null default now(),
    primary key (scope, from_source, to_source, kind)
);

-- "What overturned this decision?" walks edges backwards.
create index if not exists decision_links_target_idx
    on decision_links (scope, to_source);

create table if not exists decision_files (
    scope   text not null,
    source  text not null,
    path    text not null,
    change  text not null default '',   -- added | modified | removed | renamed
    primary key (scope, source, path)
);

-- text_pattern_ops makes `path like 'src/auth/%'` an index range scan
-- regardless of the database collation.
create index if not exists decision_files_path_idx
    on decision_files (scope, path text_pattern_ops);
