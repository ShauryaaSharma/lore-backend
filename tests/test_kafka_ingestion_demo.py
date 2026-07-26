"""Unit tests for the Kafka demo — mock the kafka client entirely, so these
run without a broker and without touching the real app.config/canon setup."""

from unittest.mock import MagicMock

from app.examples.kafka_ingestion.consumer import handle_event
from app.examples.kafka_ingestion.events import sample_event
from app.examples.kafka_ingestion.producer import publish_pr_merged
from app.examples.kafka_ingestion.settings import kafka_settings


def test_publish_pr_merged_sends_keyed_by_repo():
    producer = MagicMock()
    event = sample_event()

    publish_pr_merged(producer, event)

    producer.send.assert_called_once_with(
        kafka_settings.kafka_topic, key=event["repo_full"], value=event
    )
    producer.flush.assert_called_once()


def test_handle_event_default_does_not_touch_canon():
    # No --live: should just log, never import/call app.retrieval.canon.
    handle_event(dict(sample_event()), live=False)


def test_handle_event_live_calls_inscribe_pr(monkeypatch):
    called = {}

    def fake_inscribe_pr(scope, **kwargs):
        called["scope"] = scope
        called["kwargs"] = kwargs

    from app.retrieval import canon
    monkeypatch.setattr(canon, "inscribe_pr", fake_inscribe_pr)

    event = dict(sample_event())
    handle_event(event, live=True)

    assert called["scope"] == "gh:lorehasit"
    assert called["kwargs"]["number"] == event["number"]
    assert called["kwargs"]["repo_full"] == event["repo_full"]
