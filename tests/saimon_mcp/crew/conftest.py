"""Shared test fixtures for crew-mcp tests."""

import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_key() -> str:
    return "sk-test-crew-key"


@pytest.fixture
def client(api_key, monkeypatch):
    """Return a TestClient for the crew-mcp FastAPI app."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("saimon_mcp.crew.server", None)
    from saimon_mcp.crew.server import app

    return TestClient(app)


@pytest.fixture
def auth_headers(api_key):
    return {"X-Saimon-API-Key": api_key}
