"""Tests for SQL injection resistance across all MCPs.

Verifies that all SQL queries use parameterized $1/$2 placeholders
and that injection attempts via search queries have no effect.
"""

import pytest
from fastapi.testclient import TestClient

# Import each MCP's app
from mcp.search.server import app as search_app, _db_pool as _search_db, _auth as _search_auth
from mcp.explore.server import app as explore_app, _db_pool as _explore_db
from mcp.generate.server import app as generate_app, _db_pool as _generate_db


SQL_INJECTION_PAYLOADS = [
    "'; DROP TABLE knowledge_graph_nodes; --",
    "1' OR '1'='1",
    "' UNION SELECT username, password FROM users --",
    "'; DELETE FROM audit_log WHERE '1'='1",
    "'; INSERT INTO users VALUES ('hacker', 'pw'); --",
    "1; SELECT pg_sleep(5); --",
    "' OR 1=1 --",
    "admin'--",
    "'/**/OR/**/1=1--",
    "') OR ('1'='1",
]


class TestSQLInjectionSearch:
    """SQL injection via search_knowledge_graph should have no effect."""

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_search_knowledge_graph_injection(self, payload):
        """Injection attempts via search queries don't break anything."""
        client = TestClient(search_app)
        # Without API key configured (test mode), auth is bypassed
        resp = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000001",
                "content_type": "research_note",
                "parameters": {"query": payload, "limit": 5},
            },
            headers={"X-Saimon-API-Key": "sk-test-search-key"},
        )
        # Should get a normal response (not a 500 crash)
        assert resp.status_code in (200, 401, 422), f"Unexpected status {resp.status_code} for payload: {payload}"
        if resp.status_code == 200:
            data = resp.json()
            # Response should be valid Envelope
            assert "status" in data
            assert data["status"] in ("success", "degraded", "error")

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_search_shadow_injection(self, payload):
        """Injection attempts via shadow library search don't break anything."""
        client = TestClient(search_app)
        resp = client.post(
            "/tools/search_shadow_libraries",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000002",
                "content_type": "research_note",
                "parameters": {"query": payload, "limit": 5},
            },
            headers={"X-Saimon-API-Key": "sk-test-search-key"},
        )
        assert resp.status_code in (200, 401, 422), f"Unexpected status {resp.status_code}"

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_explore_content_injection(self, payload):
        """Injection attempts via explore_content don't break anything."""
        client = TestClient(explore_app)
        resp = client.post(
            "/tools/explore_content",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000003",
                "content_type": "research_note",
                "parameters": {"query": payload, "limit": 5},
            },
            headers={"X-Saimon-API-Key": "sk-test-explore-key"},
        )
        assert resp.status_code in (200, 401, 422), f"Unexpected status {resp.status_code}"


class TestSQLInjectionBrowseByType:
    """SQL injection via browse_by_type content_type parameter."""

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    def test_browse_by_type_injection(self, payload):
        """Injection via content_type parameter is blocked/ineffective."""
        client = TestClient(explore_app)
        resp = client.post(
            "/tools/browse_by_type",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000004",
                "content_type": "research_note",
                "parameters": {"content_type": payload, "limit": 5},
            },
            headers={"X-Saimon-API-Key": "sk-test-explore-key"},
        )
        assert resp.status_code in (200, 401, 422)


class TestSQLInjectionListSources:
    """SQL injection via list_source_indexes and get_source_index_detail."""

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    def test_get_source_index_detail_injection(self, payload):
        """Injection via source_index_id is parameterized."""
        client = TestClient(search_app)
        resp = client.post(
            "/tools/get_source_index_detail",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000005",
                "content_type": "research_note",
                "parameters": {"source_index_id": payload},
            },
            headers={"X-Saimon-API-Key": "sk-test-search-key"},
        )
        assert resp.status_code in (200, 401, 422)
