-- Control-plane schema: tenants, auth, GitHub installs/repos, jobs, dedup.
-- Lives in the same Postgres used for pgvector (when VECTOR_STORE=pgvector) —
-- one connection string, one backup, for the whole system.

create extension if not exists pgcrypto;

create table if not exists tenants (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    plan        text not null default 'free',
    created_at  timestamptz not null default now()
);

create table if not exists api_keys (
    id            uuid primary key default gen_random_uuid(),
    tenant_id     uuid not null references tenants(id) on delete cascade,
    hashed_key    text not null unique,
    scopes        text[] not null default '{read:why}',
    last_used_at  timestamptz,
    revoked_at    timestamptz,
    created_at    timestamptz not null default now()
);
create index if not exists api_keys_tenant_idx on api_keys (tenant_id);

create table if not exists installations (
    id                      uuid primary key default gen_random_uuid(),
    tenant_id               uuid not null references tenants(id) on delete cascade,
    github_installation_id  bigint not null unique,
    account_login           text not null,
    account_type            text not null check (account_type in ('org', 'user')),
    created_at              timestamptz not null default now()
);

create table if not exists repos (
    id               uuid primary key default gen_random_uuid(),
    installation_id  uuid not null references installations(id) on delete cascade,
    github_repo_id   bigint not null,
    full_name        text not null,
    backfill_state   text not null default 'pending'
                      check (backfill_state in ('pending', 'running', 'done', 'error')),
    updated_at       timestamptz not null default now(),
    unique (installation_id, github_repo_id)
);

create table if not exists jobs (
    id          bigserial primary key,
    tenant_id   uuid references tenants(id) on delete cascade,
    type        text not null,
    payload     jsonb not null default '{}',
    status      text not null default 'queued'
                check (status in ('queued', 'running', 'done', 'error')),
    attempts    int not null default 0,
    run_after   timestamptz not null default now(),
    progress    jsonb not null default '{}',
    error       text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists jobs_claimable_idx on jobs (run_after) where status = 'queued';

create table if not exists webhook_deliveries (
    delivery_id  text primary key,
    received_at  timestamptz not null default now()
);

create table if not exists idempotency_keys (
    key         text primary key,
    tenant_id   uuid,
    response    jsonb not null,
    created_at  timestamptz not null default now()
);
