"""Consumes `pr_merged` events from Kafka. Demo only — see README.md in this
directory. By default only logs what it received; pass `--live` to actually
write into the Canon via the same `inscribe_pr` the GitHub webhook path
uses, so the two ingestion paths visibly converge on one write path.

Run as `python -m lore_backend.examples.kafka_ingestion.consumer [--live]`.
"""

from __future__ import annotations

import argparse
import json
import logging

from kafka import KafkaConsumer

from lore_backend.examples.kafka_ingestion.settings import kafka_settings

logger = logging.getLogger(__name__)


def get_consumer() -> KafkaConsumer:
    return KafkaConsumer(
        kafka_settings.kafka_topic,
        bootstrap_servers=kafka_settings.kafka_bootstrap_servers,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        group_id="lore-kafka-ingestion-demo",
        auto_offset_reset="earliest",
    )


def handle_event(event: dict, live: bool) -> None:
    logger.info("received pr_merged repo=%s pr=%s title=%r",
                event.get("repo_full"), event.get("number"), event.get("title"))

    if not live:
        return

    # Deferred import: keeps this demo importable (and its dependency
    # installable) without pulling in lore_backend.config, which fails fast if
    # DATABASE_URL / GROQ_API_KEY aren't set.
    from lore_backend.retrieval import canon

    owner = (event.get("repo_full") or "").split("/")[0]
    scope = canon.account_scope(owner)
    canon.inscribe_pr(
        scope,
        number=event.get("number"),
        title=event.get("title", ""),
        body=event.get("body", ""),
        threads="",
        author=event.get("author", ""),
        repo_full=event.get("repo_full", ""),
        url=event.get("url", ""),
        merged_at=event.get("merged_at", ""),
    )
    logger.info("inscribed pr=%s into canon scope=%s", event.get("number"), scope)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                         help="write consumed events into the real Canon")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    consumer = get_consumer()
    logger.info("listening on topic=%s live=%s", kafka_settings.kafka_topic, args.live)
    for message in consumer:
        handle_event(message.value, args.live)


if __name__ == "__main__":
    main()
