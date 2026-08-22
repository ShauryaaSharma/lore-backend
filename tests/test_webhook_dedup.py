from lore_backend.ingestion.dedup import is_new_delivery


def test_first_delivery_is_new():
    assert is_new_delivery("delivery-abc") is True


def test_replayed_delivery_is_not_new():
    assert is_new_delivery("delivery-xyz") is True
    assert is_new_delivery("delivery-xyz") is False
    assert is_new_delivery("delivery-xyz") is False


def test_missing_delivery_id_always_processed():
    # No X-GitHub-Delivery header (e.g. a local curl test) — don't block it.
    assert is_new_delivery("") is True
    assert is_new_delivery("") is True
