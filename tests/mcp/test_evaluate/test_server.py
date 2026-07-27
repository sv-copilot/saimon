"""Tests for evaluate-mcp — quality gate MCP."""


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
        assert data["service"] == "evaluate-mcp"

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
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Hello world"},
            },
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        """Any tool endpoint returns 401 with a wrong API key."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Hello world"},
            },
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_tool_endpoint_accepts_correct_key(
        self, client, sample_trace_id, auth_headers
    ):
        """A valid API key allows access to tool endpoints."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Hello world"},
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
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Test content for evaluation."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "trace_id" in data
        assert "status" in data
        assert data["status"] in ("success", "error", "degraded")
        assert data["trace_id"] == sample_trace_id


# ---------------------------------------------------------------------------
# Tool: evaluate_content
# ---------------------------------------------------------------------------

class TestEvaluateContent:
    def test_requires_content(self, client, sample_trace_id, auth_headers):
        """evaluate_content returns error without content parameter."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert any("content" in e.lower() for e in (data.get("errors") or []))

    def test_defaults_to_all_criteria(self, client, sample_trace_id, auth_headers):
        """evaluate_content evaluates all criteria when none specified."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "A clear and complete evaluation target."},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "scores" in data["data"]
        # At least 5 default criteria: clarity, completeness, coherence,
        # conciseness, tone_match
        assert len(data["data"]["scores"]) >= 5

    def test_filters_by_specified_criteria(
        self, client, sample_trace_id, auth_headers
    ):
        """evaluate_content evaluates only requested criteria."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": "Test content.",
                    "criteria": ["clarity", "coherence"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "success"
        score_names = [s["criterion"] for s in data["data"]["scores"]]
        assert set(score_names) == {"clarity", "coherence"}

    def test_each_score_has_required_fields(
        self, client, sample_trace_id, auth_headers
    ):
        """Each score entry includes criterion, score, max_score, justification."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Test content."},
            },
            headers=auth_headers,
        )
        data = response.json()
        for score in data["data"]["scores"]:
            assert "criterion" in score
            assert "score" in score
            assert 0.0 <= score["score"] <= 1.0
            assert "max_score" in score
            assert score["max_score"] == 1.0
            assert "justification" in score
            assert len(score["justification"]) > 0

    def test_includes_overall_score(self, client, sample_trace_id, auth_headers):
        """evaluate_content returns an aggregate overall_score."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"content": "Test content."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "overall_score" in data["data"]
        assert 0.0 <= data["data"]["overall_score"] <= 1.0

    def test_rejects_unknown_criterion(self, client, sample_trace_id, auth_headers):
        """evaluate_content errors when an unknown criterion is requested."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": "Test content.",
                    "criteria": ["nonexistent"],
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_accepts_tone_parameter(self, client, sample_trace_id, auth_headers):
        """evaluate_content accepts optional tone for tone_match criterion."""
        response = client.post(
            "/tools/evaluate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {
                    "content": "Test content.",
                    "tone": "professional",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tool: list_criteria
# ---------------------------------------------------------------------------

class TestListCriteria:
    def test_returns_registered_criteria(self, client, sample_trace_id, auth_headers):
        """list_criteria returns all evaluation criteria."""
        response = client.post(
            "/tools/list_criteria",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert isinstance(data["data"]["criteria"], list)
        assert len(data["data"]["criteria"]) >= 5

    def test_criteria_have_schema(self, client, sample_trace_id, auth_headers):
        """Each criterion includes name, description, and weight."""
        response = client.post(
            "/tools/list_criteria",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
            },
            headers=auth_headers,
        )
        data = response.json()
        for c in data["data"]["criteria"]:
            assert "name" in c
            assert "description" in c
            assert "weight" in c
            assert 0.0 <= c["weight"] <= 1.0


# ---------------------------------------------------------------------------
# Tool: get_criterion_detail
# ---------------------------------------------------------------------------

class TestGetCriterionDetail:
    def test_returns_detail_for_known_criterion(
        self, client, sample_trace_id, auth_headers
    ):
        """get_criterion_detail returns schema for clarity."""
        response = client.post(
            "/tools/get_criterion_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"criterion_name": "clarity"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["name"] == "clarity"

    def test_errors_for_unknown_criterion(
        self, client, sample_trace_id, auth_headers
    ):
        """get_criterion_detail errors for unknown criterion."""
        response = client.post(
            "/tools/get_criterion_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
                "parameters": {"criterion_name": "nonexistent"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_errors_without_criterion_name(
        self, client, sample_trace_id, auth_headers
    ):
        """get_criterion_detail errors without criterion_name."""
        response = client.post(
            "/tools/get_criterion_detail",
            json={
                "trace_id": sample_trace_id,
                "content_type": "evaluate",
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
        """evaluate-mcp exposes ≤10 tools."""
        response = client.get("/tools", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) <= 10
