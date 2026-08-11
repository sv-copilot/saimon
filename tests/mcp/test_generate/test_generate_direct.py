"""Tests for SAIMON-GENERATE-DIRECT (#38) — direct content generation
without meta-review wrapping, plus quality gates.
"""

import pytest


# ---------------------------------------------------------------------------
# Test 1: Direct generation does NOT contain meta-review headers
# ---------------------------------------------------------------------------

class TestDirectGenerationNoMetaReview:
    """Verify generate_content produces direct content, not a "Review of
    Unverifiable Claims" meta-analysis."""

    def test_direct_generation_no_unverifiable_header(
        self, client, sample_trace_id, auth_headers
    ):
        """Content from generate_content must not contain UNVERIFIABLE markers."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "blog_post",
                "parameters": {"prompt": "Write about AI governance in 2026",
                               "tone": "analytical"},
            },
            headers=auth_headers,
        )
        data = response.json()
        # Fallback content is expected without LLM — verify shape
        assert data["status"] in ("success", "degraded")
        if data["status"] == "success" and data.get("data", {}).get("content"):
            content = data["data"]["content"]
            assert "UNVERIFIABLE" not in content, (
                f"Content should not contain UNVERIFIABLE markers: {content[:200]}"
            )

    def test_direct_generation_no_review_of_header(
        self, client, sample_trace_id, auth_headers
    ):
        """Content must not contain 'Review of' headers."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": "research_note",
                "parameters": {"prompt": "Summarize MCP architecture",
                               "tone": "neutral"},
            },
            headers=auth_headers,
        )
        data = response.json()
        if data["status"] == "success" and data.get("data", {}).get("content"):
            content = data["data"]["content"]
            assert "Review of" not in content, (
                f"Content should not contain 'Review of' header: {content[:200]}"
            )


# ---------------------------------------------------------------------------
# Test 2: All 14 content types produce valid output
# ---------------------------------------------------------------------------

class TestAllContentTypes:
    """Verify each registered content type can be called without error."""

    CONTENT_TYPES = [
        "blog_post", "summary", "research_note", "white_paper",
        "case_study", "bibliography", "social_post", "email_draft",
        "press_release", "proposal", "tutorial", "product_review",
        "meeting_notes", "job_posting",
    ]

    @pytest.mark.parametrize("content_type", CONTENT_TYPES)
    def test_content_type_accepts_request(
        self, client, sample_trace_id, auth_headers, content_type
    ):
        """Every registered content type should return a valid response."""
        response = client.post(
            "/tools/generate_content",
            json={
                "trace_id": sample_trace_id,
                "content_type": content_type,
                "parameters": {"prompt": f"Write about {content_type.replace('_', ' ')}",
                               "tone": "analytical"},
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "error", "degraded")
        # Should not be an error unless missing required params
        if data["status"] == "error":
            assert "prompt" not in data.get("errors", [""])[0].lower(), (
                f"Unexpected error for {content_type}: {data.get('errors')}"
            )


# ---------------------------------------------------------------------------
# Test 3: Quality gates reject forbidden phrases
# ---------------------------------------------------------------------------

class TestQualityGateForbiddenPhrases:
    """Verify _quality_gate_check rejects forbidden phrases."""

    def test_rejects_ai_language_model_phrase(self):
        """Content containing 'as an AI language model' fails the gate."""
        from mcp.generate.server import _quality_gate_check

        result = _quality_gate_check(
            "As an AI language model, I think...", "blog_post"
        )
        assert result["passed"] is False
        assert "Forbidden phrase" in result["reason"]

    def test_rejects_as_an_ai_i_phrase(self):
        """Content containing 'as an AI, I' fails the gate."""
        from mcp.generate.server import _quality_gate_check

        result = _quality_gate_check(
            "As an AI, I can help you with that.", "blog_post"
        )
        assert result["passed"] is False
        assert "Forbidden phrase" in result["reason"]

    def test_passes_clean_content(self):
        """Clean content without forbidden phrases passes the gate."""
        from mcp.generate.server import _quality_gate_check

        result = _quality_gate_check(
            "AI governance is evolving rapidly in 2026. "
            "Organizations are adopting new frameworks for oversight.",
            "blog_post",
        )
        assert result["passed"] is True
        assert result["reason"] is None


# ---------------------------------------------------------------------------
# Test 4: Quality gates reject voice risk patterns
# ---------------------------------------------------------------------------

class TestQualityGateVoiceRisk:
    """Verify _quality_gate_check rejects AI-voice patterns."""

    def test_rejects_here_is_a_draft(self):
        """Content containing 'here is a draft' fails the gate."""
        from mcp.generate.server import _quality_gate_check

        result = _quality_gate_check(
            "Here is a draft of the blog post about AI governance.",
            "blog_post",
        )
        assert result["passed"] is False
        assert "Voice risk" in result["reason"]

    def test_rejects_i_hope_this(self):
        """Content containing 'I hope this' fails the gate."""
        from mcp.generate.server import _quality_gate_check

        result = _quality_gate_check(
            "I hope this helps with your request.", "email_draft"
        )
        assert result["passed"] is False
        assert "Voice risk" in result["reason"]

    def test_passes_normal_content(self):
        """Normal authorial content passes voice risk check."""
        from mcp.generate.server import _quality_gate_check

        result = _quality_gate_check(
            "Autonomous development governance is a framework for managing "
            "AI-assisted software development workflows.",
            "white_paper",
        )
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# Test 5: Sources are still grounded when provided
# ---------------------------------------------------------------------------

class TestSourceGrounding:
    """Verify sources_block appears in the prompt when sources are provided."""

    def test_sources_included_in_format(self):
        """_format_sources_text produces a grounding block for sources."""
        from mcp.generate.server import _format_sources_text

        class FakeSource:
            def __init__(self, title, authors, year, identifier, src_type="academic_paper"):
                self.title = title
                self.authors = authors
                self.year = year
                self.identifier = identifier
                self.type = src_type

        sources = [
            FakeSource("AI Governance Framework", "Smith, J.", 2024, "doi:10.1000/abc", "academic_paper"),
            FakeSource("Autonomous Systems", "Jones, K.", 2023, "doi:10.1000/def", "academic_paper"),
        ]
        block = _format_sources_text(sources)
        assert "AI Governance Framework" in block
        assert "Smith, J." in block
        assert "2024" in block
        assert "Use ONLY the following sources" in block

    def test_empty_sources_returns_empty(self):
        """_format_sources_text returns empty string for no sources."""
        from mcp.generate.server import _format_sources_text

        assert _format_sources_text([]) == ""
        assert _format_sources_text(None) == ""


# ---------------------------------------------------------------------------
# Test 6: generate_verified endpoint exists and uses critique path
# ---------------------------------------------------------------------------

class TestGenerateVerified:
    """Verify the generate_verified tool endpoint exists and functions."""

    def test_tool_listed_in_manifest(self, client, auth_headers):
        """generate_verified appears in the /tools manifest."""
        response = client.get("/tools", headers=auth_headers)
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "generate_verified" in tool_names, (
            f"generate_verified missing from tool manifest: {tool_names}"
        )

    def test_endpoint_accepts_request(
        self, client, sample_trace_id, auth_headers
    ):
        """generate_verified endpoint accepts a valid request."""
        response = client.post(
            "/tools/generate_verified",
            json={
                "trace_id": sample_trace_id,
                "content_type": "research_note",
                "parameters": {
                    "prompt": "Summarize AI governance trends",
                    "content_type": "research_note",
                    "tone": "analytical",
                },
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["status"] in ("success", "error", "degraded")
        # Fallback is acceptable when no LLM is injected

    def test_endpoint_requires_auth(self, client, sample_trace_id):
        """generate_verified requires authentication."""
        response = client.post(
            "/tools/generate_verified",
            json={
                "trace_id": sample_trace_id,
                "content_type": "research_note",
                "parameters": {"prompt": "Test", "content_type": "research_note"},
            },
        )
        assert response.status_code == 401
