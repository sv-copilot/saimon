"""Tests for list_source_indexes dedupe.

The DB `sources` table already contains shadow-library rows (seeded), and
the endpoint also appends the shadow registry adapters — producing one
duplicate per shadow library. The endpoint must dedupe by (type, identifier).
"""

import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_key() -> str:
    return "sk-test-search-key"


@pytest.fixture
def client(api_key, monkeypatch):
    """Return a TestClient with a mocked DB pool containing shadow rows."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("saimon_mcp.search.server", None)
    sys.modules.pop("saimon_mcp.search", None)
    from research_shared.shadow_registry import reset_shadow_registry

    reset_shadow_registry()
    import saimon_mcp.search.server as search_server

    db_pool = MagicMock()
    db_pool.fetch = AsyncMock(
        return_value=[
            {"type": "knowledge_graph", "identifier": "kg-root", "label": "Root node"},
            {"type": "shadow_library", "identifier": "annas_archive", "label": "[Tier S] Anna's Archive"},
            {"type": "shadow_library", "identifier": "libgen", "label": "[Tier S] LibGen"},
        ]
    )
    search_server._db_pool = db_pool
    return TestClient(search_server.app)


def test_no_duplicate_source_identifiers(client, api_key):
    """The endpoint returns no duplicate (type, identifier) pairs."""
    response = client.post(
        "/tools/list_source_indexes",
        json={
            "trace_id": str(uuid.uuid4()),
            "content_type": "search",
            "parameters": {},
        },
        headers={"X-Saimon-API-Key": api_key},
    )
    assert response.status_code == 200
    indexes = response.json()["data"]["source_indexes"]
    keys = [(s.get("type"), s.get("identifier")) for s in indexes]
    assert len(keys) == len(set(keys)), f"duplicate source indexes: {keys}"
    # Shadow libraries come from the registry (with tier info), not the DB rows
    shadow = [s for s in indexes if s.get("type") == "shadow_library"]
    assert all("tier" in s for s in shadow)
