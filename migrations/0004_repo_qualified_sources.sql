-- PR decisions were stored as `PR #482`, unique per account scope. One
-- account's Canon spans many repositories, each with its own #482, so the
-- second one silently overwrote the first (`on conflict (scope, source) do
-- update`). PRs are now `owner/name#482`; this moves existing data over.
--
-- The vector store is not in Postgres, so it cannot move in this file. Each
-- rename is recorded in source_renames and applied to the store by
-- semantic.apply_source_renames() at startup, reusing the stored vectors.
-- A rename stays pending until that succeeds.

create table if not exists source_renames (
    scope       text not null,
    old_source  text not null,
    new_source  text not null,
    applied_at  timestamptz,               -- applied to the vector store
    primary key (scope, old_source)
);

create index if not exists source_renames_pending_idx
    on source_renames (scope) where applied_at is null;

insert into source_renames (scope, old_source, new_source)
select scope, source, lower(repo) || '#' || substring(source from '^PR #(\d+)$')
from decision_events
where kind = 'pr' and source ~ '^PR #\d+$' and repo <> ''
on conflict do nothing;

update decision_events e set source = r.new_source
from source_renames r
where e.scope = r.scope and e.source = r.old_source;

update decision_files f set source = r.new_source
from source_renames r
where f.scope = r.scope and f.source = r.old_source;

update decision_links l set from_source = r.new_source
from source_renames r
where l.scope = r.scope and l.from_source = r.old_source;

-- A bare `#12` in a PR meant PR 12 of that PR's own repository, and was
-- stored as `PR #12`. Qualify it the same way the extractor now does.
update decision_links l
set to_source = lower(e.repo) || '#' || substring(l.to_source from '^PR #(\d+)$')
from decision_events e
where e.scope = l.scope and e.source = l.from_source
  and l.to_source ~ '^PR #\d+$' and e.repo <> '';

-- Edges from decisions with no repository (a commit inscribed without one)
-- can still name a renamed PR; within a scope old_source is unique, so
-- follow the rename.
update decision_links l set to_source = r.new_source
from source_renames r
where l.scope = r.scope and l.to_source = r.old_source;
