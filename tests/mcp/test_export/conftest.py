"""Shared test fixtures for export-mcp tests."""

import sys
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api_key() -> str:
    return "sk-test-export-key"


@pytest.fixture
def client(api_key, monkeypatch):
    """Return a TestClient for the export-mcp FastAPI app."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("mcp.export.server", None)
    from mcp.export.server import app

    return TestClient(app)


@pytest.fixture
def auth_headers(api_key):
    """Standard auth headers for requests."""
    return {"X-Saimon-API-Key": api_key}
