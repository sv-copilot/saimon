"""Tests for search-mcp — FastAPI server providing search tools."""



# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client):
        """GET /health returns 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "search-mcp"

    def test_health_no_auth_required(self, client):
        """Health endpoint does not require auth."""
        response = client.get("/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_tool_endpoint_rejects_missing_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 without an API key."""
        response = client.post(
            "/tools/search_knowledge_graph",
            json={"trace_id": sample_trace_id, "content_type": "search"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 with a wrong API key."""
        response = client.post(
            "/tools/search_knowledge_graph",
            json={"trace_id": sample_trace_id, "content_type": "search"},
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_accepts_correct_key(
        self, client, sample_trace_id, auth_headers
    ):
        """A valid API key allows access to tool endpoints."""
        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "AI governance"},
            },
            headers=auth_headers,
        )
        # May be 200 or 422 (validation) but not 401
        assert response.status_code != 401


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

class TestEnvelope:
    def test_response_uses_research_response_shape(
        self, client, sample_trace_id, auth_headers
    ):
        """Tool responses conform to ResearchResponse envelope."""
        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "test"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "trace_id" in data
        assert "status" in data
        assert data["status"] in ("success", "error", "degraded")
        assert data["trace_id"] == sample_trace_id


# ---------------------------------------------------------------------------
# Tool: search_knowledge_graph
# ---------------------------------------------------------------------------

class TestSearchKnowledgeGraph:
    def test_accepts_query_parameter(
        self, client, sample_trace_id, auth_headers
    ):
        """search_knowledge_graph accepts a query string."""
        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "machine learning"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_accepts_limit_parameter(
        self, client, sample_trace_id, auth_headers
    ):
        """search_knowledge_graph respects an optional limit."""
        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "test", "limit": 3},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_accepts_sources_filter(
        self, client, sample_trace_id, auth_headers
    ):
        """search_knowledge_graph accepts source references."""
        response = client.post(
            "/tools/search_knowledge_graph",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "test"},
                "sources": [
                    {"type": "knowledge_graph", "identifier": "kg-root"}
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tool: search_web
# ---------------------------------------------------------------------------

class TestSearchWeb:
    def test_rejects_without_query(
        self, client, sample_trace_id, auth_headers
    ):
        """search_web requires a query parameter (fail-closed)."""
        response = client.post(
            "/tools/search_web",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {},
            },
            headers=auth_headers,
        )
        # MCP pattern: HTTP 200, error in envelope
        data = response.json()
        assert data["status"] == "error"
        assert any("query" in e.lower() for e in (data.get("errors") or []))

    def test_accepts_query(
        self, client, sample_trace_id, auth_headers
    ):
        """search_web with a valid query returns a response."""
        response = client.post(
            "/tools/search_web",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"query": "latest AI research"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tool: list_source_indexes (primary) + list_sources (deprecated alias)
# ---------------------------------------------------------------------------

class TestListSourceIndexes:
    def test_new_endpoint_returns_source_indexes(
        self, client, sample_trace_id, auth_headers
    ):
        """list_source_indexes returns available source indexes."""
        response = client.post(
            "/tools/list_source_indexes",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "source_indexes" in data["data"]

    def test_deprecated_endpoint_returns_same_data(
        self, client, sample_trace_id, auth_headers
    ):
        """list_sources (deprecated) returns same data as list_source_indexes."""
        response = client.post(
            "/tools/list_sources",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_deprecated_endpoint_has_deprecation_header(
        self, client, sample_trace_id, auth_headers
    ):
        """list_sources (deprecated) returns X-Deprecated header."""
        response = client.post(
            "/tools/list_sources",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers.get("X-Deprecated") == "true"


# ---------------------------------------------------------------------------
# Tool: get_source_index_detail (primary) + get_source_detail (deprecated alias)
# ---------------------------------------------------------------------------

class TestGetSourceIndexDetail:
    def test_new_endpoint_returns_source_index_metadata(
        self, client, sample_trace_id, auth_headers
    ):
        """get_source_index_detail returns metadata for a source index."""
        response = client.post(
            "/tools/get_source_index_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"source_index_id": "kg-root"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_new_endpoint_rejects_missing_source_index_id(
        self, client, sample_trace_id, auth_headers
    ):
        """get_source_index_detail returns error without source_index_id."""
        response = client.post(
            "/tools/get_source_index_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("source_index_id" in e.lower() for e in (data.get("errors") or []))

    def test_deprecated_endpoint_accepts_source_id(
        self, client, sample_trace_id, auth_headers
    ):
        """get_source_detail (deprecated) maps source_id → source_index_id."""
        response = client.post(
            "/tools/get_source_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"source_id": "kg-root"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_deprecated_endpoint_has_deprecation_header(
        self, client, sample_trace_id, auth_headers
    ):
        """get_source_detail (deprecated) returns X-Deprecated header."""
        response = client.post(
            "/tools/get_source_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {"source_id": "kg-root"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers.get("X-Deprecated") == "true"

    def test_deprecated_endpoint_rejects_missing_source_id(
        self, client, sample_trace_id, auth_headers
    ):
        """get_source_detail (deprecated) returns error without source_id."""
        response = client.post(
            "/tools/get_source_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        # Error references the new parameter name after mapping
        assert any(
            "source_index_id" in e.lower() for e in (data.get("errors") or [])
        )


# ---------------------------------------------------------------------------
# Tool count
# ---------------------------------------------------------------------------

class TestToolCount:
    def test_tool_count_within_limit(self, client, auth_headers):
        """search-mcp exposes ≤10 tools as required by project criteria."""
        response = client.get(
            "/tools", headers=auth_headers
        )
        if response.status_code == 200:
            data = response.json()
            assert len(data["tools"]) <= 10
        elif response.status_code == 404:
            pass  # /tools listing endpoint optional
