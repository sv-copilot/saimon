"""Tests for search_archives tool — shadow library search endpoint."""

import uuid

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api_key() -> str:
    return "sk-test-shadow-search-key"


@pytest.fixture
def client(api_key, monkeypatch):
    """Return a TestClient for the search-mcp FastAPI app."""
    import sys
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    # Fresh import to pick up env vars
    sys.modules.pop("saimon_mcp.search.server", None)
    sys.modules.pop("saimon_mcp.search", None)
    # Also reset shadow registry singleton
    from research_shared.shadow_registry import reset_shadow_registry
    reset_shadow_registry()
    from saimon_mcp.search.server import app
    return TestClient(app)


@pytest.fixture
def auth_headers(api_key):
    """Standard auth headers."""
    return {"X-Saimon-API-Key": api_key}


# ---------------------------------------------------------------------------
# Tool: search_archives
# ---------------------------------------------------------------------------


class TestSearchArchives:
    """Tests for POST /tools/search_archives."""

    def test_endpoint_exists(self, client, sample_trace_id, auth_headers):
        """The endpoint returns 200 (not 404)."""
        response = client.post(
            "/tools/search_archives",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "machine learning"},
            },
            headers=auth_headers,
        )
        assert response.status_code != 404

    def test_requires_query_parameter(
        self, client, sample_trace_id, auth_headers
    ):
        """Missing query returns an error envelope, not empty results."""
        response = client.post(
            "/tools/search_archives",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert data.get("errors")
        assert any("query" in e.lower() for e in data["errors"])

    def test_returns_success_with_valid_query(
        self, client, sample_trace_id, auth_headers
    ):
        """Valid query returns success envelope with results."""
        response = client.post(
            "/tools/search_archives",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "transformer attention mechanisms"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert "results" in data["data"]
        assert "total_results" in data["data"]
        assert "query" in data["data"]

    def test_results_have_required_fields(
        self, client, sample_trace_id, auth_headers
    ):
        """Each result has type, identifier, title, source_index."""
        response = client.post(
            "/tools/search_archives",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "deep learning"},
            },
            headers=auth_headers,
        )
        data = response.json()
        for result in data["data"]["results"]:
            assert "type" in result
            assert "identifier" in result
            assert "title" in result
            assert "source_index" in result
            assert "source_index_label" in result

    def test_filter_by_source_indexes(
        self, client, sample_trace_id, auth_headers
    ):
        """source_indexes filter limits which adapters are queried."""
        response = client.post(
            "/tools/search_archives",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {
                    "query": "test",
                    "source_indexes": ["libgen"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        # All results should be from libgen
        for result in data["data"]["results"]:
            assert result["source_index"] == "libgen"

    def test_limit_parameter_respected(
        self, client, sample_trace_id, auth_headers
    ):
        """limit parameter caps the number of results."""
        response = client.post(
            "/tools/search_archives",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "test", "limit": 3},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert len(data["data"]["results"]) <= 3

    def test_empty_query_returns_error(
        self, client, sample_trace_id, auth_headers
    ):
        """Empty query returns an error envelope with a message."""
        response = client.post(
            "/tools/search_archives",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": ""},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert data.get("errors")
        assert any("query" in e.lower() for e in data["errors"])
        assert "trace_id" in data
        assert data["trace_id"] == sample_trace_id

    def test_requires_auth(self, client, sample_trace_id):
        """Unauthenticated requests get 401."""
        response = client.post(
            "/tools/search_archives",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "test"},
            },
        )
        assert response.status_code == 401

    def test_includes_shadow_sources_in_list_source_indexes(
        self, client, sample_trace_id, auth_headers
    ):
        """list_source_indexes includes shadow library entries."""
        response = client.post(
            "/tools/list_source_indexes",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
            },
            headers=auth_headers,
        )
        data = response.json()
        source_indexes = data["data"]["source_indexes"]
        types = {s.get("type") for s in source_indexes}
        assert "public_archive" in types, (
            f"Expected public_archive type in source indexes, got: {types}"
        )

    def test_tool_manifest_includes_search_archives(
        self, client, auth_headers
    ):
        """The /tools endpoint lists search_archives."""
        response = client.get("/tools", headers=auth_headers)
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert "search_archives" in tool_names
