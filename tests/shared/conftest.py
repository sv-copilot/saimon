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
