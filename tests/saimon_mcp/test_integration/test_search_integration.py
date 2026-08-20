"""Integration tests for search-mcp — DB backend wiring.

Verifies that search-mcp can be injected with a DatabasePool backend.
"""

from __future__ import annotations

import sys


def _fresh_search_app(monkeypatch, api_key):
    """Reload the search-mcp app with a fresh module state."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("saimon_mcp.search.server", None)
    from saimon_mcp.search.server import app
    return app


class TestDBBackendInjection:
    """search-mcp should support injecting a DatabasePool backend."""

    def test_set_db_pool_function_exists(self):
        """Module has set_db_pool function for dependency injection."""
        sys.modules.pop("saimon_mcp.search.server", None)
        from saimon_mcp.search import server

        assert hasattr(server, "set_db_pool"), (
            "search.server should expose set_db_pool()"
        )
        assert callable(server.set_db_pool)

    def test_search_knowledge_graph_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, search_knowledge_graph queries it."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        # Configure mock DB to return some rows
        mock_db.fetch.return_value = [
            {"id": "kg-001", "title": "AI Ethics", "relevance": 0.95},
            {"id": "kg-002", "title": "ML Governance", "relevance": 0.82},
        ]

        import saimon_mcp.search.server as server_mod
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
        assert response.status_code == 200
        mock_db.fetch.assert_called_once()
        call_sql = mock_db.fetch.call_args[0][0]
        assert "SELECT" in call_sql or "select" in call_sql.lower()

    def test_search_knowledge_graph_degraded_without_db(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Without DB injected, search_knowledge_graph returns degraded response."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        from saimon_mcp.search.server import app
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

        sys.modules.pop("saimon_mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetch.return_value = [
            {"type": "knowledge_graph", "identifier": "kg-root", "label": "Root"},
            {"type": "web_page", "identifier": "web-1", "label": "Web Source"},
        ]

        import saimon_mcp.search.server as server_mod
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
        assert response.status_code == 200
        mock_db.fetch.assert_called()

    def test_get_source_detail_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, get_source_detail queries it."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetchrow.return_value = {
            "identifier": "kg-root",
            "type": "knowledge_graph",
            "label": "Root Node",
            "node_count": 42,
        }

        import saimon_mcp.search.server as server_mod
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
        assert response.status_code == 200
        mock_db.fetchrow.assert_called()


# ---------------------------------------------------------------------------
# search_knowledge_graph user_id scoping (#61)
# ---------------------------------------------------------------------------

class TestSearchUserScoping:
    """search_knowledge_graph should filter by optional user_id."""

    def test_search_without_user_id_returns_shared_only(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """Default search (no user_id) filters to user_id IS NULL."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetch.return_value = [
            {"id": "kg-001", "title": "Shared Research", "relevance": 0.9},
        ]

        import saimon_mcp.search.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "research", "limit": 5},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        # Verify SQL includes "user_id IS NULL" clause
        mock_db.fetch.assert_called_once()
        sql = mock_db.fetch.call_args[0][0]
        assert "user_id IS NULL" in sql, (
            f"Default search should filter to shared-only: {sql}"
        )
        # Should NOT have "user_id = " (only IS NULL)
        assert "user_id = $" not in sql, (
            f"Should not include user_id = param when no user_id given: {sql}"
        )

    def test_search_with_user_id_returns_user_plus_shared(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """Search with user_id returns user's content OR shared."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.search.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetch.return_value = [
            {"id": "kg-001", "title": "Shared Research", "relevance": 0.9},
            {"id": "kg-002", "title": "Spencer Personal", "relevance": 0.8},
        ]

        import saimon_mcp.search.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        test_user_id = "bc410a6a-ca2f-4e6d-9024-2c6b0944c42f"
        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {
                    "query": "research",
                    "limit": 5,
                    "user_id": test_user_id,
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        mock_db.fetch.assert_called_once()
        sql = mock_db.fetch.call_args[0][0]
        assert "user_id = $" in sql or "user_id = $1" in sql, (
            f"Search with user_id should include user_id = param: {sql}"
        )
        assert "user_id IS NULL" in sql, (
            f"Search with user_id should also include shared: {sql}"
        )
        # Verify user_id UUID was passed as a parameter
        all_params = []
        for arg in mock_db.fetch.call_args[0]:
            all_params.append(str(arg))
        all_params_str = " ".join(all_params)
        assert test_user_id in all_params_str, (
            f"user_id {test_user_id} should be in query params: {all_params_str}"
        )
