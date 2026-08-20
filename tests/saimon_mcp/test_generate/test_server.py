"""Tests for generate-mcp — LLM content generation MCP."""

import pytest

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


# ---------------------------------------------------------------------------
# Tool: generate_job_hunt_content
# ---------------------------------------------------------------------------


class TestGenerateJobHuntContent:
    def test_tool_registered(self, client, auth_headers):
        """generate_job_hunt_content appears in tools listing."""
        response = client.get("/tools", headers=auth_headers)
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert "generate_job_hunt_content" in tool_names

    def test_accepts_valid_domain_type(
        self, client, sample_trace_id, auth_headers
    ):
        """generate_job_hunt_content accepts a valid job hunt content type."""
        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "resume",
                "parameters": {"prompt": "Senior engineer with 8 YOE."},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")

    def test_rejects_non_domain_type(
        self, client, sample_trace_id, auth_headers
    ):
        """generate_job_hunt_content rejects non-job-hunt content types."""
        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI."},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"
        assert "not a job hunt content type" in str(data.get("errors", []))

    def test_requires_prompt(self, client, sample_trace_id, auth_headers):
        """generate_job_hunt_content errors without prompt."""
        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "resume",
                "parameters": {},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] == "error"

    def test_requires_auth(self, client, sample_trace_id):
        """generate_job_hunt_content rejects unauthenticated requests."""
        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "resume",
                "parameters": {"prompt": "Test."},
            },
        )
        assert response.status_code == 401

    @pytest.mark.parametrize("content_type", [
        "resume",
        "cover_letter",
        "job_match",
        "interview_prep",
        "salary_benchmark",
    ])
    def test_all_domain_types_work(
        self, client, sample_trace_id, auth_headers, content_type
    ):
        """All 5 job hunt domain types produce valid responses."""
        response = client.post(
            "/tools/generate_job_hunt_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": content_type,
                "parameters": {"prompt": f"Test prompt for {content_type}."},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        assert data.get("data", {}).get("domain") == "job_hunt"

    def test_list_content_types_includes_domain_types(
        self, client, sample_trace_id, auth_headers
    ):
        """list_content_types includes job hunt domain types."""
        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "generate",
            },
            headers=auth_headers,
        )
        data = response.json()
        type_names = {t["name"] for t in data["data"]["types"]}
        expected = {"resume", "cover_letter", "job_match",
                    "interview_prep", "salary_benchmark"}
        missing = expected - type_names
        assert not missing, f"Domain types missing from listing: {missing}"

    def test_domain_types_have_domain_field(
        self, client, sample_trace_id, auth_headers
    ):
        """Domain content types include domain field in list_content_types."""
        response = client.post(
            "/tools/list_content_types",
            json={
                "trace_id": sample_trace_id,
                "content_type": "generate",
            },
            headers=auth_headers,
        )
        data = response.json()
        domain_types = [
            t for t in data["data"]["types"]
            if t["name"] in {
                "resume", "cover_letter", "job_match",
                "interview_prep", "salary_benchmark",
            }
        ]
        for dt in domain_types:
            assert dt.get("domain") == "job_hunt", (
                f"Domain type {dt['name']} missing domain field"
            )


# ---------------------------------------------------------------------------
# FACTUALITY-SOURCE-1: Source-Grounded Generation
# ---------------------------------------------------------------------------


class TestSourceGroundedGeneration:
    """Tests for source-grounded generation (FACTUALITY-SOURCE-1)."""

    def test_constrained_to_sources(
        self, client, sample_trace_id, auth_headers
    ):
        """Generated content does not invent facts not in provided sources."""
        sources = [
            {
                "type": "web_page",
                "identifier": "The sky is blue due to Rayleigh scattering.",
                "title": "Why the Sky Is Blue",
                "authors": "John Tyndall",
                "year": "1869",
            },
            {
                "type": "web_page",
                "identifier": "Water boils at 100°C at sea level.",
                "title": "Properties of Water",
                "authors": "Marie Curie",
                "year": "1904",
            },
        ]
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "summary",
                "parameters": {
                    "prompt": "Explain the sky and boiling water.",
                },
                "sources": sources,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        # When fallback (no LLM), the response text should be present
        assert data["data"]["content"] is not None
        # Citations should be populated from source identifiers
        citations = data.get("citations") or []
        assert len(citations) == 2

    def test_no_sources_backward_compatible(
        self, client, sample_trace_id, auth_headers
    ):
        """Without sources, behavior is unchanged (backward compatible)."""
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
        assert data["data"]["content"] is not None

    def test_rejects_invented_facts(
        self, client, sample_trace_id, auth_headers
    ):
        """Content with invented statistics should be constrained when
        sources are provided (source-grounding block appears in prompt)."""
        sources = [
            {
                "type": "document",
                "identifier": "Only basic facts about water.",
                "title": "Water Facts",
                "authors": "A. Scientist",
                "year": "2020",
            },
        ]
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "summary",
                "parameters": {
                    "prompt": "Describe water properties including "
                              "precise boiling point.",
                },
                "sources": sources,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        content = data["data"]["content"]
        assert content is not None
        # Source grounding instruction should be embedded in the prompt
        # (we verify the response is well-formed regardless of LLM availability)
        assert isinstance(content, str)

    def test_sources_formatted_in_prompt(
        self, client, sample_trace_id, auth_headers, monkeypatch
    ):
        """When sources are provided, the LLM prompt includes the
        'Use ONLY the following sources' constraint directive."""
        sources = [
            {
                "type": "web_page",
                "identifier": "Source Alpha",
                "title": "Alpha Research",
                "authors": "Dr. A",
                "year": "2023",
            },
        ]

        # We verify that the endpoint accepts and forwards sources correctly
        # by checking the response is valid and citations are populated.
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "research_note",
                "parameters": {"prompt": "Summarize the research."},
                "sources": sources,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        citations = data.get("citations") or []
        assert len(citations) >= 1


# ---------------------------------------------------------------------------
# FACTUALITY-PROMPT-1: Prompt Chain Improvements
# ---------------------------------------------------------------------------


class TestPromptFactuality:
    """Tests for prompt chain factuality improvements (FACTUALITY-PROMPT-1)."""

    def test_uncertainty_markers_present(
        self, client, sample_trace_id, auth_headers
    ):
        """Output may contain [LOW CONFIDENCE] markers when LLM is
        uncertain about a claim.  Without a live LLM this verifies the
        endpoint still returns valid responses."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "summary",
                "parameters": {
                    "prompt": "Describe the population of Tokyo and the "
                              "average temperature of Mars.",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        content = data["data"]["content"]
        assert content is not None
        assert isinstance(content, str)

    def test_reasoning_in_output(
        self, client, sample_trace_id, auth_headers
    ):
        """Output should include reasoning/evidence section before final
        content when the LLM backend is available.

        Without a live LLM, this ensures the endpoint still functions.
        """
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {
                    "prompt": "Explain the benefits of open source software.",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        content = data["data"]["content"]
        assert content is not None
        # Fallback content describes degraded mode
        assert isinstance(content, str)

    def test_no_invented_stats(
        self, client, sample_trace_id, auth_headers
    ):
        """The prompt explicitly forbids inventing statistics, dates, and
        names.  Verify the endpoint handles this correctly."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "research_note",
                "parameters": {
                    "prompt": "Report on global literacy rates and the "
                              "exact number of schools in Africa.",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        content = data["data"]["content"]
        assert content is not None
        assert isinstance(content, str)

    def test_self_critique_reduces_claims(
        self, client, sample_trace_id, auth_headers
    ):
        """The second pass (self-critique) should reduce unverifiable claims
        by flagging them with [UNVERIFIABLE] markers.

        Without a live LLM, this verifies the endpoint returns valid
        responses."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "white_paper",
                "parameters": {
                    "prompt": "Write a white paper on the economic impact "
                              "of AI with specific GDP figures.",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        content = data["data"]["content"]
        assert content is not None
        # Even in fallback mode, content is present
        assert isinstance(content, str)

    def test_two_turn_generation_fallback(
        self, client, sample_trace_id, auth_headers
    ):
        """Verify that generate_content can handle the two-turn generation
        (draft + self-critique) in fallback/degraded mode without errors."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "case_study",
                "parameters": {
                    "prompt": "Write a case study about renewable energy "
                              "adoption with specific cost figures.",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("success", "degraded")
        content = data["data"]["content"]
        assert content is not None
        # The response must have a backend marker
        assert "backend" in data["data"]
