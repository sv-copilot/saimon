"""Tests for explore-mcp — discovery MCP."""


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
        assert data["service"] == "explore-mcp"

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
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "AI governance"},
            },
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 with a wrong API key."""
        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "AI governance"},
            },
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_accepts_correct_key(
        self, client, sample_trace_id, auth_headers
    ):
        """A valid API key allows access to tool endpoints."""
        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "AI governance"},
            },
            headers=auth_headers,
        )
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
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
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
# Tool: explore_content
# ---------------------------------------------------------------------------

class TestExploreContent:
    def test_requires_query(self, client, sample_trace_id, auth_headers):
        """explore_content returns error without query parameter."""
        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("query" in e.lower() for e in (data.get("errors") or []))

    def test_returns_results_with_query(
        self, client, sample_trace_id, auth_headers
    ):
        """explore_content returns discovery results for a valid query."""
        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "AI governance frameworks"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert "results" in data["data"]
        assert isinstance(data["data"]["results"], list)

    def test_results_have_required_fields(
        self, client, sample_trace_id, auth_headers
    ):
        """Each result includes id, title, content_type, relevance."""
        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "machine learning"},
            },
            headers=auth_headers,
        )
        data = response.json()
        for item in data["data"]["results"]:
            assert "id" in item
            assert "title" in item
            assert "content_type" in item
            assert "relevance" in item
            assert 0.0 <= item["relevance"] <= 1.0

    def test_respects_limit_parameter(
        self, client, sample_trace_id, auth_headers
    ):
        """explore_content respects the limit parameter."""
        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "data science", "limit": 3},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert len(data["data"]["results"]) <= 3

    def test_includes_query_in_response(
        self, client, sample_trace_id, auth_headers
    ):
        """explore_content echoes back the query in the response."""
        response = client.post(
            "/tools/explore_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"query": "neural networks"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["data"]["query"] == "neural networks"


# ---------------------------------------------------------------------------
# Tool: browse_by_type
# ---------------------------------------------------------------------------

class TestBrowseByType:
    def test_requires_content_type(self, client, sample_trace_id, auth_headers):
        """browse_by_type returns error without content_type parameter."""
        response = client.post(
            "/tools/browse_by_type",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any(
            "content_type" in e.lower() for e in (data.get("errors") or [])
        )

    def test_returns_items_for_valid_type(
        self, client, sample_trace_id, auth_headers
    ):
        """browse_by_type returns items for a valid content type."""
        response = client.post(
            "/tools/browse_by_type",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"content_type": "article"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert "items" in data["data"]
        assert isinstance(data["data"]["items"], list)

    def test_items_have_required_fields(
        self, client, sample_trace_id, auth_headers
    ):
        """Each browsed item has id, title, summary."""
        response = client.post(
            "/tools/browse_by_type",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"content_type": "research_note"},
            },
            headers=auth_headers,
        )
        data = response.json()
        for item in data["data"]["items"]:
            assert "id" in item
            assert "title" in item
            assert "summary" in item

    def test_respects_limit_and_offset(
        self, client, sample_trace_id, auth_headers
    ):
        """browse_by_type supports pagination with limit and offset."""
        response = client.post(
            "/tools/browse_by_type",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {
                    "content_type": "article",
                    "limit": 2,
                    "offset": 1,
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert len(data["data"]["items"]) <= 2


# ---------------------------------------------------------------------------
# Tool: get_related
# ---------------------------------------------------------------------------

class TestGetRelated:
    def test_requires_node_id(self, client, sample_trace_id, auth_headers):
        """get_related returns error without node_id parameter."""
        response = client.post(
            "/tools/get_related",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any(
            "node_id" in e.lower() for e in (data.get("errors") or [])
        )

    def test_returns_related_items(
        self, client, sample_trace_id, auth_headers
    ):
        """get_related returns items related to a given node_id."""
        response = client.post(
            "/tools/get_related",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"node_id": "kg-001"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Accept error (no DB) or success (with DB)
        assert data["status"] in ("success", "degraded", "error")
        if data["status"] == "error":
            assert "database" in str(data.get("errors", "")).lower()
        else:
            assert "related" in data["data"]
            assert isinstance(data["data"]["related"], list)

    def test_related_items_have_relationship_field(
        self, client, sample_trace_id, auth_headers
    ):
        """Each related item includes a relationship type."""
        response = client.post(
            "/tools/get_related",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"node_id": "kg-001"},
            },
            headers=auth_headers,
        )
        data = response.json()
        # Skip structural assertions when DB is unavailable
        if data["status"] == "error" and "database" in str(data.get("errors", "")).lower():
            return
        for item in data["data"]["related"]:
            assert "id" in item
            assert "title" in item
            assert "relationship" in item
            assert item["relationship"] in (
                "cites", "extends", "contradicts", "supports", "references"
            )

    def test_handles_unknown_node_id(
        self, client, sample_trace_id, auth_headers
    ):
        """get_related returns empty list for unknown node_id."""
        response = client.post(
            "/tools/get_related",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {"node_id": "nonexistent-99999"},
            },
            headers=auth_headers,
        )
        data = response.json()
        # Accept error (no DB) or success (with DB)
        assert data["status"] in ("success", "degraded", "error")
        if data["status"] == "error":
            assert "database" in str(data.get("errors", "")).lower()
        else:
            assert data["data"]["related"] == []


# ---------------------------------------------------------------------------
# Tool: discover_connections
# ---------------------------------------------------------------------------

class TestDiscoverConnections:
    def test_requires_source_and_target(
        self, client, sample_trace_id, auth_headers
    ):
        """discover_connections returns error without source_id and target_id."""
        response = client.post(
            "/tools/discover_connections",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        errors_lower = " ".join(data.get("errors") or []).lower()
        assert "source_id" in errors_lower
        assert "target_id" in errors_lower

    def test_discovers_path_between_nodes(
        self, client, sample_trace_id, auth_headers
    ):
        """discover_connections finds paths between two knowledge graph nodes."""
        response = client.post(
            "/tools/discover_connections",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {
                    "source_id": "kg-001",
                    "target_id": "kg-005",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert "paths" in data["data"]
        assert isinstance(data["data"]["paths"], list)

    def test_paths_have_nodes_and_edges(
        self, client, sample_trace_id, auth_headers
    ):
        """Each path contains nodes and edges lists."""
        response = client.post(
            "/tools/discover_connections",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {
                    "source_id": "kg-001",
                    "target_id": "kg-005",
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        for path in data["data"]["paths"]:
            assert "nodes" in path
            assert "edges" in path
            assert isinstance(path["nodes"], list)
            assert isinstance(path["edges"], list)

    def test_handles_no_path_found(
        self, client, sample_trace_id, auth_headers
    ):
        """discover_connections returns empty paths when no connection exists."""
        response = client.post(
            "/tools/discover_connections",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {
                    "source_id": "isolated-node",
                    "target_id": "another-isolated",
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["data"]["paths"] == []


# ---------------------------------------------------------------------------
# Tool: list_content_types
# ---------------------------------------------------------------------------

class TestListContentTypes:
    def test_returns_all_content_types(
        self, client, sample_trace_id, auth_headers
    ):
        """list_content_types returns all registered content types."""
        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert "content_types" in data["data"]
        assert isinstance(data["data"]["content_types"], list)

    def test_each_type_has_name_and_description(
        self, client, sample_trace_id, auth_headers
    ):
        """Each content type includes name, description, and count."""
        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        for ct in data["data"]["content_types"]:
            assert "name" in ct
            assert "description" in ct
            assert "item_count" in ct
            assert isinstance(ct["item_count"], int)
            assert ct["item_count"] >= 0

    def test_includes_known_types(self, client, sample_trace_id, auth_headers):
        """list_content_types includes expected platform content types."""
        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "explore",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        names = [ct["name"] for ct in data["data"]["content_types"]]
        assert "blog_post" in names
        assert "research_note" in names


# ---------------------------------------------------------------------------
# Tool: tool manifest
# ---------------------------------------------------------------------------

class TestToolManifest:
    def test_returns_all_six_tools(self, client, auth_headers):
        """GET /tools returns the 6-tool manifest (including create_edge)."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        tool_names = [t["name"] for t in data["tools"]]
        assert len(tool_names) == 6
        assert "explore_content" in tool_names
        assert "browse_by_type" in tool_names
        assert "get_related" in tool_names
        assert "discover_connections" in tool_names
        assert "list_content_types" in tool_names
        assert "create_edge" in tool_names

    def test_manifest_requires_auth(self, client):
        """GET /tools returns 401 without auth."""
        response = client.get("/tools")
        assert response.status_code == 401
