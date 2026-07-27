"""Integration tests for search-mcp — DB backend wiring.

Verifies that search-mcp can be injected with a DatabasePool backend.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest


def _fresh_search_app(monkeypatch, api_key):
    """Reload the search-mcp app with a fresh module state."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("mcp.search.server", None)
    from mcp.search.server import app
    return app


class TestDBBackendInjection:
    """search-mcp should support injecting a DatabasePool backend."""

    def test_set_db_pool_function_exists(self):
        """Module has set_db_pool function for dependency injection."""
        sys.modules.pop("mcp.search.server", None)
        from mcp.search import server

        assert hasattr(server, "set_db_pool"), (
            "search.server should expose set_db_pool()"
        )
        assert callable(server.set_db_pool)

    def test_search_knowledge_graph_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, search_knowledge_graph queries it."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        # Configure mock DB to return some rows
        mock_db.fetch.return_value = [
            {"id": "kg-001", "title": "AI Ethics", "relevance": 0.95},
            {"id": "kg-002", "title": "ML Governance", "relevance": 0.82},
        ]

        import mcp.search.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "AI ethics", "limit": 5},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        mock_db.fetch.assert_called_once()
        call_sql = mock_db.fetch.call_args[0][0]
        assert "SELECT" in call_sql or "select" in call_sql.lower()

    def test_search_knowledge_graph_degraded_without_db(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Without DB injected, search_knowledge_graph returns degraded response."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        from mcp.search.server import app
        client = TestClient(app)

        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "test"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_list_sources_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, list_sources queries it."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetch.return_value = [
            {"type": "knowledge_graph", "identifier": "kg-root", "label": "Root"},
            {"type": "web_page", "identifier": "web-1", "label": "Web Source"},
        ]

        import mcp.search.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/list_sources",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        mock_db.fetch.assert_called()

    def test_get_source_detail_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, get_source_detail queries it."""
        from fastapi.testclient import TestClient

        sys.modules.pop("mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetchrow.return_value = {
            "identifier": "kg-root",
            "type": "knowledge_graph",
            "label": "Root Node",
            "node_count": 42,
        }

        import mcp.search.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/get_source_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"source_id": "kg-root"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        mock_db.fetchrow.assert_called()
