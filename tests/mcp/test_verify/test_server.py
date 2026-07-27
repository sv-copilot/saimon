"""Tests for verify-mcp — fact-checking MCP."""


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
        assert data["service"] == "verify-mcp"

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
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 with a wrong API key."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_accepts_correct_key(
        self, client, sample_trace_id, auth_headers
    ):
        """A valid API key allows access to tool endpoints."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
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
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "trace_id" in data
        assert "status" in data
        assert data["status"] in ("success", "error", "degraded")
        assert data["trace_id"] == sample_trace_id


# ---------------------------------------------------------------------------
# Tool: verify_claim
# ---------------------------------------------------------------------------

class TestVerifyClaim:
    def test_requires_claim(self, client, sample_trace_id, auth_headers):
        """verify_claim returns error without claim parameter."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("claim" in e.lower() for e in (data.get("errors") or []))

    def test_verifies_claim_with_default_methods(
        self, client, sample_trace_id, auth_headers
    ):
        """verify_claim returns verification results with default methods."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth revolves around the Sun."},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "verifications" in data["data"]
        assert len(data["data"]["verifications"]) >= 2

    def test_filters_by_specified_methods(
        self, client, sample_trace_id, auth_headers
    ):
        """verify_claim uses only requested verification methods."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "claim": "Water boils at 100°C at sea level.",
                    "methods": ["source_corroboration", "logical_consistency"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        method_names = [v["method"] for v in data["data"]["verifications"]]
        assert set(method_names) == {"source_corroboration", "logical_consistency"}

    def test_each_verification_has_required_fields(
        self, client, sample_trace_id, auth_headers
    ):
        """Each verification includes method, verdict, confidence, explanation."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "Python was created by Guido van Rossum."},
            },
            headers=auth_headers,
        )
        data = response.json()
        for v in data["data"]["verifications"]:
            assert "method" in v
            assert "verdict" in v
            assert v["verdict"] in ("supported", "refuted", "inconclusive")
            assert "confidence" in v
            assert 0.0 <= v["confidence"] <= 1.0
            assert "explanation" in v
            assert len(v["explanation"]) > 0

    def test_includes_overall_verdict(self, client, sample_trace_id, auth_headers):
        """verify_claim returns an aggregate overall_verdict."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "The Earth is round."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "overall_verdict" in data["data"]
        assert data["data"]["overall_verdict"] in (
            "supported", "refuted", "inconclusive"
        )

    def test_rejects_unknown_method(self, client, sample_trace_id, auth_headers):
        """verify_claim errors when an unknown method is requested."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {
                    "claim": "Test claim.",
                    "methods": ["nonexistent_method"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_accepts_sources_for_corroboration(
        self, client, sample_trace_id, auth_headers
    ):
        """verify_claim accepts optional sources list."""
        response = client.post(
            "/tools/verify_claim",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"claim": "Test claim."},
                "sources": [
                    {"type": "web_page", "identifier": "https://example.com"}
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tool: list_verification_methods
# ---------------------------------------------------------------------------

class TestListVerificationMethods:
    def test_returns_registered_methods(
        self, client, sample_trace_id, auth_headers
    ):
        """list_verification_methods returns all methods."""
        response = client.post(
            "/tools/list_verification_methods",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert isinstance(data["data"]["methods"], list)
        assert len(data["data"]["methods"]) >= 3

    def test_methods_have_schema(self, client, sample_trace_id, auth_headers):
        """Each method includes name, description, and reliability."""
        response = client.post(
            "/tools/list_verification_methods",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
            },
            headers=auth_headers,
        )
        data = response.json()
        for m in data["data"]["methods"]:
            assert "name" in m
            assert "description" in m
            assert "reliability" in m
            assert 0.0 <= m["reliability"] <= 1.0


# ---------------------------------------------------------------------------
# Tool: get_method_detail
# ---------------------------------------------------------------------------

class TestGetMethodDetail:
    def test_returns_detail_for_known_method(
        self, client, sample_trace_id, auth_headers
    ):
        """get_method_detail returns schema for source_corroboration."""
        response = client.post(
            "/tools/get_method_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"method_name": "source_corroboration"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["name"] == "source_corroboration"

    def test_errors_for_unknown_method(
        self, client, sample_trace_id, auth_headers
    ):
        """get_method_detail errors for unknown method."""
        response = client.post(
            "/tools/get_method_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
                "parameters": {"method_name": "nonexistent"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_errors_without_method_name(
        self, client, sample_trace_id, auth_headers
    ):
        """get_method_detail errors without method_name."""
        response = client.post(
            "/tools/get_method_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "verify",
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
        """verify-mcp exposes ≤10 tools."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) <= 10
