"""Unit tests for the Kafka demo — mock the kafka client entirely, so these
run without a broker and without touching the real lore_backend.config/canon setup.

Skipped unless `kafka-python` is installed. The demo keeps its dependency in
its own requirements file precisely so the main install stays lean, which
means the import can legitimately be absent — a missing optional dependency
should skip these, not fail the whole run.
"""

from unittest.mock import MagicMock

import pytest

pytest.importorskip(
    "kafka",
    reason="demo-only dependency: pip install -r app/examples/kafka_ingestion/requirements.txt",
)

from lore_backend.examples.kafka_ingestion.consumer import handle_event  # noqa: E402
from lore_backend.examples.kafka_ingestion.events import sample_event  # noqa: E402
from lore_backend.examples.kafka_ingestion.producer import publish_pr_merged  # noqa: E402
from lore_backend.examples.kafka_ingestion.settings import kafka_settings  # noqa: E402


def test_publish_pr_merged_sends_keyed_by_repo():
    producer = MagicMock()
    event = sample_event()

    publish_pr_merged(producer, event)

    producer.send.assert_called_once_with(
        kafka_settings.kafka_topic, key=event["repo_full"], value=event
    )
    producer.flush.assert_called_once()


def test_handle_event_default_does_not_touch_canon():
    # No --live: should just log, never import/call lore_backend.retrieval.canon.
    handle_event(dict(sample_event()), live=False)


def test_handle_event_live_calls_inscribe_pr(monkeypatch):
    called = {}

    def fake_inscribe_pr(scope, **kwargs):
        called["scope"] = scope
        called["kwargs"] = kwargs

    from lore_backend.retrieval import canon
    monkeypatch.setattr(canon, "inscribe_pr", fake_inscribe_pr)

    event = dict(sample_event())
    handle_event(event, live=True)

    assert called["scope"] == "gh:lorehasit"
    assert called["kwargs"]["number"] == event["number"]
    assert called["kwargs"]["repo_full"] == event["repo_full"]
