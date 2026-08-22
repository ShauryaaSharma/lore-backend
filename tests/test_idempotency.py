from lore_backend.storage.queries import get_idempotent_response, store_idempotent_response


def test_first_write_is_stored():
    assert get_idempotent_response("key-1") is None
    store_idempotent_response("key-1", None, {"inscribed": True})
    assert get_idempotent_response("key-1") == {"inscribed": True}


def test_second_write_with_same_key_does_not_overwrite():
    store_idempotent_response("key-2", None, {"attempt": 1})
    store_idempotent_response("key-2", None, {"attempt": 2})
    assert get_idempotent_response("key-2") == {"attempt": 1}


def test_inscribe_endpoint_is_idempotent(client):
    headers = {"Idempotency-Key": "commit-abc123"}
    body = {"hash": "abc123", "message": "fix bug", "why": "regression", "repo": "acme/app"}

    first = client.post("/v1/inscribe", json=body, headers=headers)
    second = client.post("/v1/inscribe", json=body, headers=headers)

    assert first.status_code == 200
    assert first.json() == second.json()
