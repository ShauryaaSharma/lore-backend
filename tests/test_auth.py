from lore_backend.auth.keys import create_key, resolve, revoke


def test_create_key_resolves_to_its_tenant_scope():
    raw_key, tenant_id = create_key("acme-inc", ["read:why"])
    auth = resolve(raw_key)

    assert auth is not None
    assert auth.tenant_id == tenant_id
    assert auth.scope == "gh:acme-inc"
    assert auth.has_scope("read:why")
    assert not auth.has_scope("admin:backfill")


def test_unknown_key_does_not_resolve():
    assert resolve("lk_not_a_real_key") is None


def test_revoked_key_no_longer_resolves():
    raw_key, _ = create_key("beta-corp", ["read:why"])
    auth = resolve(raw_key)
    revoke(auth.key_id)

    assert resolve(raw_key) is None


def test_admin_scope_grants_everything():
    raw_key, _ = create_key("gamma-llc", ["admin"])
    auth = resolve(raw_key)

    assert auth.has_scope("read:why")
    assert auth.has_scope("admin:backfill")
