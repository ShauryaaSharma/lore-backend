-- Website (web/) sign-in. users/accounts/sessions/verification_token are the
-- exact tables @auth/pg-adapter expects; it hardcodes their names and columns.

create table if not exists users (
    id              serial primary key,
    name            varchar(255),
    email           varchar(255),
    "emailVerified" timestamptz,
    image           text
);

create table if not exists accounts (
    id                  serial primary key,
    "userId"            integer not null references users(id) on delete cascade,
    type                varchar(255) not null,
    provider            varchar(255) not null,
    "providerAccountId" varchar(255) not null,
    refresh_token       text,
    access_token        text,
    expires_at          bigint,
    id_token            text,
    scope               text,
    session_state       text,
    token_type          text
);

create table if not exists sessions (
    id             serial primary key,
    "userId"       integer not null references users(id) on delete cascade,
    expires        timestamptz not null,
    "sessionToken" varchar(255) not null
);

create table if not exists verification_token (
    identifier text not null,
    expires    timestamptz not null,
    token      text not null,
    primary key (identifier, token)
);

-- One Lore API key per GitHub account (the Canon's tenant), shared by every
-- website user who proved access to that account's App installation.
create table if not exists web_lore_accounts (
    login           text primary key,
    installation_id bigint not null,
    lore_key_enc    text not null,
    created_at      timestamptz not null default now()
);

create table if not exists web_user_accounts (
    user_id    integer not null references users(id) on delete cascade,
    login      text not null references web_lore_accounts(login) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (user_id, login)
);
