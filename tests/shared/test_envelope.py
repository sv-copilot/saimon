"""Tests for research_shared.envelope — typed request/response contracts."""

import uuid

import pytest

from research_shared.envelope import (
    ErrorCode,
    ResearchRequest,
    ResearchResponse,
    SourceReference,
)


class TestErrorCode:
    def test_error_codes_exist(self):
        """All expected error codes are defined."""
        codes = {e.value for e in ErrorCode}
        assert "VALIDATION_ERROR" in codes
        assert "LLM_ERROR" in codes
        assert "DB_ERROR" in codes
        assert "AUTH_ERROR" in codes
        assert "TIMEOUT" in codes

    def test_error_code_is_string_enum(self):
        """ErrorCode values are strings for JSON serialisation."""
        assert isinstance(ErrorCode.VALIDATION_ERROR.value, str)


class TestSourceReference:
    def test_minimal_source(self):
        """A SourceReference with only required fields constructs."""
        ref = SourceReference(type="knowledge_graph", identifier="doc-42")
        assert ref.type == "knowledge_graph"
        assert ref.identifier == "doc-42"
        assert ref.relevance_score is None

    def test_full_source(self):
        """A SourceReference with all fields constructs."""
        ref = SourceReference(
            type="web_page",
            identifier="https://example.com",
            relevance_score=0.95,
        )
        assert ref.type == "web_page"
        assert ref.identifier == "https://example.com"
        assert ref.relevance_score == 0.95

    def test_relevance_score_clamped(self):
        """relevance_score is validated 0.0–1.0."""
        with pytest.raises(ValueError):
            SourceReference(type="doc", identifier="x", relevance_score=1.5)
        with pytest.raises(ValueError):
            SourceReference(type="doc", identifier="x", relevance_score=-0.1)

    def test_serialise_deserialise(self):
        """SourceReference round-trips through JSON."""
        ref = SourceReference(
            type="knowledge_graph", identifier="doc-1", relevance_score=0.8
        )
        data = ref.model_dump()
        restored = SourceReference(**data)
        assert restored == ref


class TestResearchRequest:
    def test_minimal_request(self, sample_trace_id):
        """A request with only required fields constructs."""
        req = ResearchRequest(
            trace_id=sample_trace_id,
            content_type="blog_post",
        )
        assert req.trace_id == sample_trace_id
        assert req.content_type == "blog_post"
        assert req.parameters == {}
        assert req.sources == []

    def test_request_with_parameters(self, sample_trace_id):
        """parameters accepts arbitrary key-value data."""
        req = ResearchRequest(
            trace_id=sample_trace_id,
            content_type="research_note",
            parameters={"topic": "AI governance", "depth": 3},
        )
        assert req.parameters["topic"] == "AI governance"
        assert req.parameters["depth"] == 3

    def test_request_with_sources(self, sample_trace_id):
        """sources accepts a list of SourceReference objects."""
        src = SourceReference(type="knowledge_graph", identifier="kg-1")
        req = ResearchRequest(
            trace_id=sample_trace_id,
            content_type="summary",
            sources=[src],
        )
        assert len(req.sources) == 1
        assert req.sources[0].identifier == "kg-1"

    def test_request_serialise(self, sample_trace_id):
        """ResearchRequest serialises to JSON."""
        req = ResearchRequest(
            trace_id=sample_trace_id,
            content_type="blog_post",
            parameters={"tone": "professional"},
        )
        data = req.model_dump()
        assert data["trace_id"] == sample_trace_id
        assert data["content_type"] == "blog_post"
        assert data["parameters"] == {"tone": "professional"}

    def test_trace_id_must_be_valid_uuid(self):
        """trace_id must be a valid UUID string."""
        with pytest.raises(ValueError):
            ResearchRequest(trace_id="not-a-uuid", content_type="x")

    def test_content_type_must_not_be_empty(self):
        """content_type is required and non-empty."""
        tid = str(uuid.uuid4())
        with pytest.raises(ValueError):
            ResearchRequest(trace_id=tid, content_type="")


class TestResearchResponse:
    def test_success_response(self, sample_trace_id):
        """A successful response carries data and citations."""
        resp = ResearchResponse(
            trace_id=sample_trace_id,
            status="success",
            data="Generated content here",
            citations=["https://source1.com", "https://source2.com"],
        )
        assert resp.status == "success"
        assert resp.data == "Generated content here"
        assert len(resp.citations) == 2
        assert resp.errors is None

    def test_error_response(self, sample_trace_id):
        """An error response carries errors instead of data."""
        resp = ResearchResponse(
            trace_id=sample_trace_id,
            status="error",
            data=None,
            errors=["LLM timeout after 30s"],
        )
        assert resp.status == "error"
        assert resp.errors == ["LLM timeout after 30s"]
        assert resp.data is None

    def test_degraded_response(self, sample_trace_id):
        """A degraded response carries both data and errors."""
        resp = ResearchResponse(
            trace_id=sample_trace_id,
            status="degraded",
            data="Partial result",
            errors=["One source unavailable"],
            citations=["https://source1.com"],
        )
        assert resp.status == "degraded"
        assert resp.data == "Partial result"
        assert resp.errors == ["One source unavailable"]
        assert len(resp.citations) == 1

    def test_response_serialise(self, sample_trace_id):
        """ResearchResponse serialises to JSON."""
        resp = ResearchResponse(
            trace_id=sample_trace_id,
            status="success",
            data={"key": "value"},
        )
        data = resp.model_dump()
        assert data["status"] == "success"
        assert data["data"] == {"key": "value"}

    def test_invalid_status_rejected(self, sample_trace_id):
        """status must be one of success/error/degraded."""
        with pytest.raises(ValueError):
            ResearchResponse(trace_id=sample_trace_id, status="pending")
