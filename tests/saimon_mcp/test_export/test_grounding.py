"""Tests for export-mcp grounding propagation (SAIMON-GROUNDING-BINDING-1)."""


class TestExportPropagatesGrounding:
    def test_export_content_echoes_grounding(
        self, client, sample_trace_id, auth_headers
    ):
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {
                    "content": "Hello world",
                    "format": "json",
                    "grounding": "synthesis_informed",
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["grounding"] == "synthesis_informed"

    def test_export_content_omits_grounding_when_absent(
        self, client, sample_trace_id, auth_headers
    ):
        response = client.post(
            "/tools/export_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"content": "Hello world", "format": "markdown"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        assert "grounding" not in data["data"]
