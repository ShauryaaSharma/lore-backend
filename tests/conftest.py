import os

# Must happen before any `app.*` import: `app.config.settings` is built at
# import time and requires DATABASE_URL to validate.
os.environ.setdefault("DATABASE_URL", "postgresql://lore:lore@localhost:5432/lore")
os.environ.setdefault("VECTOR_STORE", "qdrant")  # keep the Canon itself dependency-light in tests
os.environ.setdefault("LORE_ADMIN_SECRET", "test-admin-secret")

import pytest  # noqa: E402

from app.storage.db import get_conn, run_migrations  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _migrated_db():
    run_migrations()
    yield


@pytest.fixture(autouse=True)
def _clean_control_plane():
    """Truncate control-plane tables between tests so they don't leak state
    into each other (jobs/api_keys/etc. are cheap to reset each time)."""
    yield
    with get_conn() as conn:
        conn.execute(
            "truncate table jobs, webhook_deliveries, idempotency_keys, "
            "api_keys, installations, repos, tenants restart identity cascade"
        )
        conn.commit()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
