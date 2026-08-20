"""Shared fixtures for MCP integration tests.

Provides mock LLMClient and DatabasePool instances for verifying
backend wiring without needing a live DB or LLM endpoint.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock LLM Client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm() -> MagicMock:
    """Return a mock LLMClient with an AsyncMock generate method."""
    mock = MagicMock()
    mock.generate = AsyncMock(return_value="Mock LLM response for testing.")
    return mock


# ---------------------------------------------------------------------------
# Mock Database Pool
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db() -> MagicMock:
    """Return a mock DatabasePool with all AsyncMock methods."""
    mock = MagicMock()
    mock.fetch = AsyncMock(return_value=[])
    mock.fetchrow = AsyncMock(return_value=None)
    mock.fetchval = AsyncMock(return_value=None)
    mock.execute = AsyncMock(return_value="OK")
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api_key() -> str:
    return "sk-test-integration-key"


@pytest.fixture
def auth_headers(api_key: str) -> dict[str, str]:
    return {"X-Saimon-API-Key": api_key}
