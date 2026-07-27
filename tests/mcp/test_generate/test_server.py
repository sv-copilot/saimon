"""Tests for generate-mcp — LLM content generation MCP."""


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
        assert data["service"] == "generate-mcp"

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
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI"},
            },
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 with a wrong API key."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI"},
            },
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_accepts_correct_key(
        self, client, sample_trace_id, auth_headers
    ):
        """A valid API key allows access."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI"},
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
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "trace_id" in data
        assert "status" in data
        assert data["status"] in ("success", "error", "degraded")
        assert data["trace_id"] == sample_trace_id


# ---------------------------------------------------------------------------
# Tool: generate_content
# ---------------------------------------------------------------------------

class TestGenerateContent:
    def test_requires_prompt(self, client, sample_trace_id, auth_headers):
        """generate_content returns error without a prompt."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert any("prompt" in e.lower() for e in (data.get("errors") or []))

    def test_requires_content_type(self, client, sample_trace_id, auth_headers):
        """generate_content returns error with empty content_type."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "",
                "parameters": {"prompt": "Write about AI"},
            },
            headers=auth_headers,
        )
        # FastAPI validates min_length=1 on content_type → 422
        assert response.status_code in (200, 422)

    def test_accepts_valid_prompt(self, client, sample_trace_id, auth_headers):
        """generate_content with valid prompt returns success (placeholder)."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI governance"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["data"] is not None

    def test_accepts_tone_parameter(self, client, sample_trace_id, auth_headers):
        """generate_content accepts optional tone parameter."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {
                    "prompt": "Write about AI",
                    "tone": "professional",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_returns_citations(self, client, sample_trace_id, auth_headers):
        """generate_content returns citations when sources are provided."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI"},
                "sources": [
                    {"type": "knowledge_graph", "identifier": "kg-ai-concept"}
                ],
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "degraded")
        citations = data.get("citations") or []
        assert len(citations) > 0


# ---------------------------------------------------------------------------
# Tool: list_content_types
# ---------------------------------------------------------------------------

class TestListContentTypes:
    def test_returns_registered_types(self, client, sample_trace_id, auth_headers):
        """list_content_types returns known content types."""
        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "generate",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert isinstance(data["data"]["types"], list)
        assert len(data["data"]["types"]) >= 3  # at least blog_post, summary, research_note

    def test_types_have_schema(self, client, sample_trace_id, auth_headers):
        """Each type includes required parameter schemas."""
        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "generate",
            },
            headers=auth_headers,
        )
        data = response.json()
        for ct in data["data"]["types"]:
            assert "name" in ct
            assert "description" in ct
            assert "required_params" in ct


# ---------------------------------------------------------------------------
# Tool: get_content_type_schema
# ---------------------------------------------------------------------------

class TestGetContentTypeSchema:
    def test_returns_schema_for_known_type(
        self, client, sample_trace_id, auth_headers
    ):
        """get_content_type_schema returns schema for blog_post."""
        response = client.post(
            "/tools/get_content_type_schema",
            json={
                "trace_id": sample_trace_id,
                "content_type": "generate",
                "parameters": {"type_name": "blog_post"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["data"]["name"] == "blog_post"

    def test_errors_for_unknown_type(self, client, sample_trace_id, auth_headers):
        """get_content_type_schema errors for unknown type."""
        response = client.post(
            "/tools/get_content_type_schema",
            json={
                "trace_id": sample_trace_id,
                "content_type": "generate",
                "parameters": {"type_name": "nonexistent_type"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_errors_without_type_name(self, client, sample_trace_id, auth_headers):
        """get_content_type_schema errors without type_name."""
        response = client.post(
            "/tools/get_content_type_schema",
            json={
                "trace_id": sample_trace_id,
                "content_type": "generate",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# Tool count
# ---------------------------------------------------------------------------

class TestToolCount:
    def test_tool_count_within_limit(self, client, auth_headers):
        """generate-mcp exposes ≤10 tools."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) <= 10
