"""Shared test fixtures for search-mcp tests."""

import sys
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api_key() -> str:
    return "sk-test-search-key"


@pytest.fixture
def client(api_key, monkeypatch):
    """Return a TestClient for the search-mcp FastAPI app."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    # Ensure a fresh import — the module reads env vars at import time.
    sys.modules.pop("saimon_mcp.search.server", None)
    sys.modules.pop("saimon_mcp.search", None)
    from saimon_mcp.search.server import app

    return TestClient(app)


@pytest.fixture
def auth_headers(api_key):
    """Standard auth headers for requests."""
    return {"X-Saimon-API-Key": api_key}
