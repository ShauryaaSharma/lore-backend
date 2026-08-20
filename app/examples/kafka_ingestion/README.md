# Kafka ingestion — demo only

This module is **not wired into the real ingestion path**. Lore's actual
ingestion is the GitHub webhook (`app/ingestion/webhook_handler.py`) feeding
a Postgres job queue (`app/jobs/queue.py`) — see
[ARCHITECTURE.md](../../../ARCHITECTURE.md):

> A modular monolith on purpose — no Kafka, no service mesh, no sharding in
> the real ingestion path.

That's still true. This module exists to show what a streaming ingestion
path *would* look like if a future integration needed one — e.g. a
higher-volume event source (CI events, bulk repo backfills across many
tenants) where a Postgres-polled queue stops being the right fit. It is
deliberately isolated from `app/ingestion`, `app/jobs`, and `app/config` so
it can be deleted without touching the production system.

## What's here

- `producer.py` — publishes a `pr_merged` event (same shape the GitHub
  webhook handler captures) to a Kafka topic.
- `consumer.py` — subscribes to that topic and parses each event. By
  default it only logs what it received; pass `--live` to actually call
  `app.retrieval.canon.inscribe_pr(...)`, the same function the webhook
  path calls, so you can see the two ingestion paths converge on the same
  write — which now means the same write-through into episodic *and*
  semantic memory.
- `settings.py` — its own tiny `KafkaSettings`, separate from
  `app.config.Settings`, so running this demo never changes how the real
  app boots or what env vars it requires.

## Running it locally

```bash
# 1. Start a local broker (Redpanda — Kafka-API compatible, no ZooKeeper,
#    one container). Only needed for this demo.
docker compose -f docker-compose.yml -f docker-compose.kafka.yml up -d redpanda

# 2. Install the extra dependency (kept out of requirements.txt on purpose)
pip install -r app/examples/kafka_ingestion/requirements.txt

# 3. In one terminal — consume
python -m app.examples.kafka_ingestion.consumer

# 4. In another — produce a sample event
python -m app.examples.kafka_ingestion.producer --sample
```

Env vars (all optional, sensible localhost defaults):

| Var | Default |
|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:19092` |
| `KAFKA_TOPIC` | `lore.pr_merged` |
