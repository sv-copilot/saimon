"""Integration tests for explore-mcp — DB and seed_data wiring.

Verifies that explore-mcp can be injected with a DatabasePool backend
and uses seed_data.py for content type definitions.
"""

from __future__ import annotations

import sys


class TestDBBackendInjection:
    """explore-mcp should support injecting a DatabasePool."""

    def test_set_db_pool_function_exists(self):
        """Module has set_db_pool function."""
        sys.modules.pop("saimon_mcp.explore.server", None)
        import saimon_mcp.explore.server as server_mod

        assert hasattr(server_mod, "set_db_pool")
        assert callable(server_mod.set_db_pool)

    def test_explore_content_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, explore_content queries it."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.explore.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetch.return_value = [
            {"id": "kg-001", "title": "AI Ethics", "content_type": "research_note", "relevance": 0.95},
            {"id": "kg-002", "title": "ML Basics", "content_type": "article", "relevance": 0.80},
        ]

        import saimon_mcp.explore.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "AI", "limit": 5},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        mock_db.fetch.assert_called()

    def test_explore_content_degraded_without_db(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """Without DB injected, explore_content degrades gracefully."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.explore.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.explore.server as server_mod
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "test"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_browse_by_type_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, browse_by_type queries it filtered."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.explore.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetch.return_value = [
            {"id": "kg-010", "title": "Note 1", "content_type": "research_note"},
        ]

        import saimon_mcp.explore.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/browse_by_type",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"content_type": "research_note", "limit": 5},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_db.fetch.assert_called()

    def test_get_related_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, get_related queries the graph."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.explore.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetch.return_value = [
            {
                "edge_id": "e-001",
                "relation_type": "cites",
                "weight": 1.0,
                "source_id": "kg-001",
                "target_id": "kg-002",
                "node_id": "kg-002",
                "title": "Related 1",
                "content_type": "research_note",
            },
        ]

        import saimon_mcp.explore.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/get_related",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"node_id": "kg-001"},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_db.fetch.assert_called()

    def test_discover_connections_uses_db_when_injected(
        self, monkeypatch, api_key, sample_trace_id, mock_db
    ):
        """When DB is injected, discover_connections runs graph traversal."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.explore.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        mock_db.fetch.return_value = [
            {"from_id": "kg-001", "to_id": "kg-002", "type": "references"},
        ]

        import saimon_mcp.explore.server as server_mod
        server_mod._db_pool = mock_db
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/discover_connections",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {
                    "source_id": "kg-001",
                    "target_id": "kg-002",
                },
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        mock_db.fetch.assert_called()


class TestSeedDataContentTypes:
    """explore-mcp should source content types from seed_data.py."""

    def test_list_content_types_uses_seed_data(
        self, monkeypatch, api_key, sample_trace_id
    ):
        """list_content_types returns types from seed_data."""
        from fastapi.testclient import TestClient

        sys.modules.pop("saimon_mcp.explore.server", None)
        monkeypatch.setenv("SAIMON_API_KEY", api_key)

        import saimon_mcp.explore.server as server_mod
        client = TestClient(server_mod.app)

        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {},
            },
            headers={"X-Saimon-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        types = data["data"]["content_types"]
        assert len(types) > 5  # Should have all 13 seed types
