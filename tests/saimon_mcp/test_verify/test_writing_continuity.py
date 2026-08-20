"""Server smoke tests for the verify_against_kg MCP tool."""


class TestWritingContinuityTool:
    def test_tool_listed(self, client, auth_headers):
        """verify_against_kg appears in the verify MCP tool manifest."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        tools = response.json()["tools"]
        assert any(t["name"] == "verify_against_kg" for t in tools)

    def test_requires_scene_text(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/verify_against_kg",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"universe_id": "universe-1"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("scene_text" in e.lower() for e in (data.get("errors") or []))

    def test_requires_universe_id(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/verify_against_kg",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"scene_text": "Mara Voss walked in."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any(
            "universe_id" in e.lower() for e in (data.get("errors") or [])
        )

    def test_returns_findings_envelope(self, client, sample_trace_id, auth_headers):
        """No DB is injected, so the tool returns an empty findings list."""
        response = client.post(
            "/tools/verify_against_kg",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "scene_text": "Mara Voss walked in.",
                    "universe_id": "universe-1",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data["trace_id"] == sample_trace_id
        assert "findings" in data["data"]
        assert data["data"]["findings"] == []
