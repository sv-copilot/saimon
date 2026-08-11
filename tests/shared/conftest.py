"""Shared test fixtures for research_shared tests."""

import os
import uuid

import pytest


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def clean_env(monkeypatch):
    """Remove all SAIMON_ env vars for isolated tests."""
    for key in list(os.environ):
        if key.startswith("SAIMON_"):
            monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def mock_api_key_env(monkeypatch):
    """Set a fake SAIMON_API_KEY for auth/llm tests."""
    monkeypatch.setenv("SAIMON_API_KEY", "sk-test-mock-key-12345")
    yield


@pytest.fixture
def mock_db_url_env(monkeypatch):
    """Set a fake DATABASE_URL for db tests."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@localhost:5432/saimon_test",
    )
    yield


# ---------------------------------------------------------------------------
# Real DB fixture — skips if no DATABASE_URL or DB unreachable
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_pool():
    """Return a connected DatabasePool, or skip the test if DB unavailable.

    Set DATABASE_URL in the environment to run these tests against
    a real PostgreSQL instance.  Tests using this fixture are skipped
    in CI without a database.
    """
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        pytest.skip("DATABASE_URL not set — skipping DB tests")

    from research_shared.db import DatabasePool

    pool = DatabasePool(database_url)
    try:
        await pool.connect()
        # Verify basic connectivity
        await pool.fetch("SELECT 1")
    except Exception as exc:
        await pool.close()
        pytest.skip(f"Database unreachable: {exc}")

    yield pool

    # Cleanup
    try:
        await pool.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# pytest marker: skip_db_if_unavailable
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "skip_db_if_unavailable: mark test as requiring a real PostgreSQL database",
    )


def pytest_collection_modifyitems(config, items):
    """If DATABASE_URL is not set, skip all tests marked skip_db_if_unavailable."""
    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        return  # DB is available, don't skip

    skip_marker = pytest.mark.skip(
        reason="DATABASE_URL not set — skipping DB-dependent tests"
    )
    for item in items:
        if item.get_closest_marker("skip_db_if_unavailable"):
            item.add_marker(skip_marker)
