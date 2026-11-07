"""Tests for the generate-mcp ``fill_gaps`` tool endpoint.

SAIMON-AUTO-SEED-LOOP-1 exposes the gap → seed → verify loop as
``/tools/fill_gaps``.  These tests verify the tool is wired into the manifest
and enforces auth + fail-closed behavior (no DB → error envelope).
"""


class TestFillGapsTool:
    def test_tool_listed_in_manifest(self, client, auth_headers):
        """fill_gaps appears in the /tools manifest."""
        response = client.get("/tools", headers=auth_headers)
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "fill_gaps" in tool_names, (
            f"fill_gaps missing from tool manifest: {tool_names}"
        )

    def test_endpoint_requires_auth(self, client, sample_trace_id):
        """fill_gaps requires authentication."""
        response = client.post(
            "/tools/fill_gaps",
            json={
                "trace_id": sample_trace_id,
                "content_type": "fill_gaps",
                "parameters": {},
            },
        )
        assert response.status_code == 401

    def test_endpoint_fails_closed_without_db(
        self, client, sample_trace_id, auth_headers
    ):
        """fill_gaps returns an error envelope when no DB is injected."""
        response = client.post(
            "/tools/fill_gaps",
            json={
                "trace_id": sample_trace_id,
                "content_type": "fill_gaps",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert "Database not available" in data["errors"][0]
