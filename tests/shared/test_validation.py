"""Tests for research_shared.validation — input validation and payload hardening."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from research_shared.validation import (
    ValidationError,
    create_payload_size_middleware,
    get_max_payload_bytes,
    get_max_query_length,
    get_max_string_length,
    set_valid_content_types,
    validate_content_type,
    validate_query,
    validate_string_length,
    validation_error_response,
)


class TestValidateStringLength:
    def test_valid_string(self):
        """String within limit passes."""
        result = validate_string_length("hello", max_length=10)
        assert result == "hello"

    def test_string_at_limit(self):
        """String exactly at limit passes."""
        result = validate_string_length("1234567890", max_length=10)
        assert result == "1234567890"

    def test_string_over_limit_raises(self):
        """String over limit raises ValidationError."""
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validate_string_length("12345678901", max_length=10)

    def test_default_max_length(self):
        """Uses configured default max length."""
        # Default is 10000 — short string should pass
        result = validate_string_length("short")
        assert result == "short"

    def test_very_long_string_blocked(self):
        """Very long strings are blocked."""
        long_str = "x" * 20000
        with pytest.raises(ValidationError):
            validate_string_length(long_str)


class TestValidateQuery:
    def test_valid_query(self):
        """Normal query passes."""
        result = validate_query("what is AI?")
        assert result == "what is AI?"

    def test_long_query_blocked(self):
        """Overly long query is blocked."""
        long_query = "x" * 2000
        with pytest.raises(ValidationError):
            validate_query(long_query)


class TestValidateContentType:
    def test_valid_type(self):
        """Registered content type passes."""
        set_valid_content_types({"blog_post", "summary", "research_note"})
        result = validate_content_type("blog_post")
        assert result == "blog_post"

    def test_invalid_type_blocked(self):
        """Unregistered content type is rejected."""
        set_valid_content_types({"blog_post", "summary"})
        with pytest.raises(ValidationError, match="Unknown content type"):
            validate_content_type("attack_type")

    def test_empty_whitelist_allows_all(self):
        """When whitelist is empty, all types are allowed (degraded mode)."""
        set_valid_content_types(set())
        result = validate_content_type("anything")
        assert result == "anything"

    def test_case_sensitive(self):
        """Content type validation is case-sensitive."""
        set_valid_content_types({"BlogPost"})
        with pytest.raises(ValidationError):
            validate_content_type("blogpost")


class TestPayloadSizeMiddleware:
    def test_small_payload_passes(self):
        """Payload within size limit passes."""
        app = FastAPI()
        PayloadSizeMiddleware = create_payload_size_middleware()
        app.add_middleware(PayloadSizeMiddleware)

        @app.post("/test")
        async def test_endpoint(request: Request):
            body = await request.json()
            return {"received": body}

        client = TestClient(app)
        resp = client.post("/test", json={"data": "small"}, headers={"Content-Length": "100"})
        assert resp.status_code == 200

    def test_large_payload_blocked(self, monkeypatch):
        """Payload over limit returns 413."""
        monkeypatch.setenv("SAIMON_MAX_PAYLOAD_BYTES", "100")
        app = FastAPI()
        PayloadSizeMiddleware = create_payload_size_middleware()
        app.add_middleware(PayloadSizeMiddleware)

        @app.post("/test")
        async def test_endpoint(request: Request):
            return {"ok": True}

        client = TestClient(app)
        # Simulate a large payload via Content-Length
        resp = client.post("/test", json={}, headers={"Content-Length": "2000000"})
        assert resp.status_code == 413
        data = resp.json()
        assert data["status"] == "error"
        assert "Payload too large" in data["errors"][0]

    def test_missing_content_length_passes(self):
        """Request without Content-Length header passes."""
        app = FastAPI()
        PayloadSizeMiddleware = create_payload_size_middleware()
        app.add_middleware(PayloadSizeMiddleware)

        @app.post("/test")
        async def test_endpoint(request: Request):
            return {"ok": True}

        client = TestClient(app)
        resp = client.post("/test", json={"data": "test"})
        assert resp.status_code == 200


class TestValidationErrorResponse:
    def test_format(self):
        """Validation error response matches Envelope format."""
        resp = validation_error_response("trace-123", "Invalid input")
        assert resp.status_code == 422
        import json
        body = json.loads(resp.body)
        assert body["status"] == "error"
        assert body["trace_id"] == "trace-123"
        assert "Invalid input" in body["errors"][0]
        assert body["data"] is None


class TestGetLimits:
    def test_default_limits(self):
        """Default limits are sensible."""
        assert get_max_payload_bytes() == 1024 * 1024  # 1MB
        assert get_max_string_length() == 10000
        assert get_max_query_length() == 1000
