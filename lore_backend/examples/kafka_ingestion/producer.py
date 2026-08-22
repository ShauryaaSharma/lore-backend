"""Publishes `pr_merged` events to Kafka. Demo only — see README.md in this
directory. Run as `python -m lore_backend.examples.kafka_ingestion.producer --sample`.
"""

from __future__ import annotations

import argparse
import json
import logging

from kafka import KafkaProducer

from lore_backend.examples.kafka_ingestion.events import PrMergedEvent, sample_event
from lore_backend.examples.kafka_ingestion.settings import kafka_settings

logger = logging.getLogger(__name__)


def get_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=kafka_settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )


def publish_pr_merged(producer: KafkaProducer, event: PrMergedEvent) -> None:
    """Keyed by repo so all merges for one repo land on the same partition —
    preserves per-repo ordering if the topic is ever scaled to >1 partition."""
    producer.send(kafka_settings.kafka_topic, key=event["repo_full"], value=event)
    producer.flush()
    logger.info("published pr_merged repo=%s pr=%s", event["repo_full"], event["number"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true",
                         help="publish one canned sample event and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    producer = get_producer()
    if args.sample:
        publish_pr_merged(producer, sample_event())
    producer.close()


if __name__ == "__main__":
    main()
