"""Tests for export-mcp — output formatting MCP."""


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
        assert data["service"] == "export-mcp"

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
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "Hello world", "format": "markdown"},
            },
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 with a wrong API key."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "Hello world", "format": "markdown"},
            },
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_accepts_correct_key(
        self, client, sample_trace_id, auth_headers
    ):
        """A valid API key allows access to tool endpoints."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "Hello world", "format": "markdown"},
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
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "Test content", "format": "plain_text"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "trace_id" in data
        assert "status" in data
        assert data["status"] in ("success", "error", "degraded")
        assert data["trace_id"] == sample_trace_id


# ---------------------------------------------------------------------------
# Tool: export_content
# ---------------------------------------------------------------------------

class TestExportContent:
    def test_requires_content(self, client, sample_trace_id, auth_headers):
        """export_content returns error without content parameter."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"format": "markdown"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("content" in e.lower() for e in (data.get("errors") or []))

    def test_requires_format(self, client, sample_trace_id, auth_headers):
        """export_content returns error without format parameter."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "Hello world"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("format" in e.lower() for e in (data.get("errors") or []))

    def test_rejects_unknown_format(self, client, sample_trace_id, auth_headers):
        """export_content errors on unsupported format."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "Hello", "format": "pdf"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_export_markdown(self, client, sample_trace_id, auth_headers):
        """export_content formats content as markdown."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "# Hello\nWorld", "format": "markdown"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert "content" in data["data"]
        assert data["data"]["format"] == "markdown"

    def test_export_plain_text(self, client, sample_trace_id, auth_headers):
        """export_content formats content as plain text."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "# Hello\nWorld", "format": "plain_text"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["format"] == "plain_text"

    def test_export_json(self, client, sample_trace_id, auth_headers):
        """export_content formats content as JSON."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "Hello world", "format": "json"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["format"] == "json"

    def test_export_html(self, client, sample_trace_id, auth_headers):
        """export_content formats content as HTML."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "# Hello\nWorld", "format": "html"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["format"] == "html"

    def test_returns_citations(self, client, sample_trace_id, auth_headers):
        """export_content returns citations when sources are provided."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"content": "Hello world", "format": "markdown"},
                "sources": [
                    {"type": "knowledge_graph", "identifier": "kg-test"}
                ],
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        citations = data.get("citations") or []
        assert len(citations) > 0

    def test_accepts_options_parameter(self, client, sample_trace_id, auth_headers):
        """export_content accepts optional format-specific options."""
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {
                    "content": "Hello world",
                    "format": "markdown",
                    "include_title": True,
                    "include_citations": True,
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tool: list_formats
# ---------------------------------------------------------------------------

class TestListFormats:
    def test_returns_registered_formats(self, client, sample_trace_id, auth_headers):
        """list_formats returns available export formats."""
        response = client.post(
            "/tools/list_formats",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert isinstance(data["data"]["formats"], list)
        # at least markdown, plain_text, json, html
        assert len(data["data"]["formats"]) >= 4

    def test_formats_have_schema(self, client, sample_trace_id, auth_headers):
        """Each format includes a description and options."""
        response = client.post(
            "/tools/list_formats",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
            },
            headers=auth_headers,
        )
        data = response.json()
        for fmt in data["data"]["formats"]:
            assert "name" in fmt
            assert "description" in fmt
            assert "options" in fmt


# ---------------------------------------------------------------------------
# Tool: get_format_schema
# ---------------------------------------------------------------------------

class TestGetFormatSchema:
    def test_returns_schema_for_known_format(
        self, client, sample_trace_id, auth_headers
    ):
        """get_format_schema returns schema for markdown."""
        response = client.post(
            "/tools/get_format_schema",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"format_name": "markdown"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["name"] == "markdown"

    def test_errors_for_unknown_format(
        self, client, sample_trace_id, auth_headers
    ):
        """get_format_schema errors for unknown format."""
        response = client.post(
            "/tools/get_format_schema",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
                "parameters": {"format_name": "nonexistent"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_errors_without_format_name(
        self, client, sample_trace_id, auth_headers
    ):
        """get_format_schema errors without format_name."""
        response = client.post(
            "/tools/get_format_schema",
            json={
                "trace_id": sample_trace_id,
                "content_type": "export",
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
        """export-mcp exposes ≤10 tools."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) <= 10
