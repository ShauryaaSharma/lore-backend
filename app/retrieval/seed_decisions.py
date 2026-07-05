"""Curated decision corpus used in MOCK mode (no API keys required).

In LIVE mode these same decisions are loaded into real mem0 memory by
`ingest_seed()`, so the extension behaves identically whether or not a
Groq key is present — mock mode simply skips the LLM and vector store.

Each entry:
  id      - stable slug
  title   - short decision headline (shown in the extension's memory list)
  meta    - "<area> · <date>"
  keys    - keywords used by the mock retriever
  answer  - the reasoning returned for /why (plain text)
  sources - list of [kind, label]; kind in {PR, incident, ADR, RFC, thread}
"""

SEED_DECISIONS = [
    {
        "id": "auth-tokens",
        "title": "Short-lived JWTs over server sessions",
        "meta": "auth · Mar 2025",
        "keys": ["auth", "token", "tokens", "jwt", "session", "sessions",
                 "login", "logout", "refresh", "redis", "stateless"],
        "answer": (
            "We moved off server-side sessions in March 2025 after an incident where a "
            "Redis failover logged every user out at once. Short-lived JWTs plus refresh "
            "tokens removed that single point of failure and let auth scale horizontally "
            "without shared session state. Priya pushed back on refresh-token rotation "
            "complexity — we accepted that cost in exchange for the availability win, and "
            "documented the rotation flow in the retro."
        ),
        "sources": [["PR", "#482 — Move to JWT access tokens"],
                    ["incident", "#incidents — session-store outage"],
                    ["RFC", "RFC-07 — Token lifetime"]],
    },
    {
        "id": "monolith",
        "title": "Kept the monolith, split only payments",
        "meta": "architecture · Nov 2024",
        "keys": ["monolith", "microservice", "microservices", "service", "services",
                 "split", "payments", "architecture", "repo", "deploy", "extract"],
        "answer": (
            "We deliberately did not break the app into microservices. At our size the "
            "operational overhead outweighed the benefits, and two earlier extraction "
            "attempts stalled. We carved out only payments into its own service because its "
            "compliance and deploy cadence genuinely differ from the rest of the product. "
            "Marcus argued for a full split; we agreed to revisit once the team passes ~40 "
            "engineers."
        ),
        "sources": [["ADR", "ADR-007 — service boundaries"],
                    ["PR", "#311 — extract payments"],
                    ["thread", "#arch-review"]],
    },
    {
        "id": "postgres",
        "title": "Postgres over MongoDB for the core DB",
        "meta": "data · Aug 2024",
        "keys": ["database", "db", "postgres", "postgresql", "mongo", "mongodb",
                 "sql", "nosql", "schema", "data", "relational"],
        "answer": (
            "We chose Postgres over MongoDB for the primary datastore. Our data is highly "
            "relational (users, teams, billing) and we wanted strong constraints and "
            "transactions rather than application-enforced integrity. We'd been burned by "
            "schema drift on a prior Mongo project. Lena kept JSONB in play for the few "
            "semi-structured fields, so we get document-style flexibility where we actually "
            "need it without giving up relational guarantees."
        ),
        "sources": [["ADR", "ADR-004 — primary datastore"],
                    ["thread", "#data-eng"]],
    },
    {
        "id": "queue",
        "title": "Managed SQS over self-hosted Kafka",
        "meta": "infra · Jan 2025",
        "keys": ["queue", "kafka", "sqs", "events", "messaging", "stream", "broker",
                 "infra", "async", "dlq", "dead-letter"],
        "answer": (
            "We picked managed SQS instead of running Kafka ourselves. Our throughput is "
            "nowhere near where Kafka's ordering and replay guarantees pay for their "
            "operational cost, and no one wanted to be on-call for a Kafka cluster. After the "
            "retry-backoff bug hid an outage, we added a dead-letter queue so failures "
            "surface instead of silently retrying. Dev flagged that if event-sourcing becomes "
            "core we'll reassess."
        ),
        "sources": [["ADR", "ADR-009 — messaging layer"],
                    ["PR", "#517 — retry queue to dead-letter"],
                    ["thread", "#backend"]],
    },
    {
        "id": "feature-flags",
        "title": "Built feature flags in-house",
        "meta": "platform · Feb 2025",
        "keys": ["feature", "flag", "flags", "launchdarkly", "rollout", "toggle",
                 "experiment", "build", "buy"],
        "answer": (
            "We built a lightweight in-house feature-flag system rather than buying "
            "LaunchDarkly. Our needs were simple (boolean + percentage rollouts) and the "
            "per-seat pricing didn't justify it at our size. Priya set the explicit tripwire: "
            "if we ever need targeting rules or experimentation analytics, we buy instead of "
            "extending the homegrown one — we don't want to accidentally build a flags platform."
        ),
        "sources": [["ADR", "ADR-011 — flags build-vs-buy"],
                    ["PR", "#699 — flag service"]],
    },
    {
        "id": "rendering",
        "title": "SSR for marketing, SPA for the app",
        "meta": "frontend · Dec 2024",
        "keys": ["ssr", "render", "rendering", "next", "frontend", "seo",
                 "marketing", "spa", "client", "performance"],
        "answer": (
            "The marketing site uses server-side rendering while the product app stays a "
            "client-side SPA. SEO and first-paint matter for marketing pages and don't for the "
            "authenticated app. Marcus initially wanted one unified SPA, but the SEO hit on "
            "marketing was unacceptable — splitting rendering strategy by surface was the "
            "pragmatic call."
        ),
        "sources": [["ADR", "ADR-006 — rendering strategy"],
                    ["thread", "#frontend"]],
    },
]
