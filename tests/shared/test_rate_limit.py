"""Tests for research_shared.rate_limit — sliding window rate limiter."""

import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from research_shared.rate_limit import (
    RateLimitExceededError,
    SlidingWindowRateLimiter,
    create_rate_limit_middleware,
    rate_limit_exceeded_response,
)


class TestSlidingWindowRateLimiter:
    def test_allows_requests_within_limit(self):
        """Requests within the limit are allowed."""
        rl = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint(request: Request):
            retry = rl.check(request)
            if retry is not None:
                return rate_limit_exceeded_response(retry_after=retry)
            return {"ok": True}

        client = TestClient(app)
        for _ in range(5):
            resp = client.get("/test")
            assert resp.status_code == 200

    def test_blocks_requests_over_limit(self):
        """Requests over the limit are blocked with 429."""
        rl = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint(request: Request):
            retry = rl.check(request)
            if retry is not None:
                return rate_limit_exceeded_response(retry_after=retry)
            return {"ok": True}

        client = TestClient(app)
        # First 3 succeed
        for _ in range(3):
            resp = client.get("/test")
            assert resp.status_code == 200

        # 4th is blocked
        resp = client.get("/test")
        assert resp.status_code == 429
        data = resp.json()
        assert data["status"] == "error"
        assert "Rate limit exceeded" in data["errors"][0]
        assert "Retry-After" in resp.headers

    def test_different_keys_separate_buckets(self):
        """Different API keys get separate rate limit buckets."""
        rl = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)

        # Key A uses all its requests
        class FakeRequestA:
            headers = {"x-saimon-api-key": "key-a"}
            url = type("URL", (), {"path": "/test"})()

        class FakeRequestB:
            headers = {"x-saimon-api-key": "key-b"}
            url = type("URL", (), {"path": "/test"})()

        # Burn key-a's budget
        assert rl.check(FakeRequestA()) is None
        assert rl.check(FakeRequestA()) is None
        assert rl.check(FakeRequestA()) is not None  # blocked

        # Key B still has budget
        assert rl.check(FakeRequestB()) is None

    def test_reset_clears_bucket(self):
        """Reset clears the rate limit bucket(s)."""
        rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)

        class FakeReq:
            headers = {"x-saimon-api-key": "test-key"}
            url = type("URL", (), {"path": "/test"})()

        # First request OK
        assert rl.check(FakeReq()) is None
        # Second blocked
        assert rl.check(FakeReq()) is not None
        # Reset
        rl.reset("test-key")
        # Now allowed again
        assert rl.check(FakeReq()) is None

    def test_reset_all(self):
        """Reset all clears all buckets."""
        rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)

        class FakeReq:
            headers = {"x-saimon-api-key": "test-key"}
            url = type("URL", (), {"path": "/test"})()

        rl.check(FakeReq())
        assert rl.bucket_count == 1
        rl.reset()
        assert rl.bucket_count == 0

    def test_from_env_defaults(self, monkeypatch):
        """Builds from environment with sensible defaults."""
        rl = SlidingWindowRateLimiter.from_env()
        assert rl.max_requests == 100
        assert rl.window_seconds == 60.0

    def test_from_env_custom(self, monkeypatch):
        """Respects SAIMON_RATE_LIMIT_* env vars."""
        monkeypatch.setenv("SAIMON_RATE_LIMIT_MAX", "50")
        monkeypatch.setenv("SAIMON_RATE_LIMIT_WINDOW", "30")
        rl = SlidingWindowRateLimiter.from_env()
        assert rl.max_requests == 50
        assert rl.window_seconds == 30.0

    def test_health_path_exempt_in_middleware(self):
        """Health endpoint is exempt from rate limiting."""
        rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
        RateLimitMiddleware = create_rate_limit_middleware(rl)
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        @app.get("/tools/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        # Health always works
        for _ in range(10):
            resp = client.get("/health")
            assert resp.status_code == 200


class TestRateLimitExceededResponse:
    def test_response_format(self):
        """429 response matches the Envelope format."""
        resp = rate_limit_exceeded_response(trace_id="abc-123", retry_after=30)
        assert resp.status_code == 429
        data = resp.body  # bytes in TestClient
        import json
        body = json.loads(data)
        assert body["status"] == "error"
        assert body["trace_id"] == "abc-123"
        assert body["data"] is None
        assert body["citations"] is None


class TestRateLimitExceededError:
    def test_error_message(self):
        """RateLimitExceededError has useful message."""
        err = RateLimitExceededError("hash123", 42)
        assert "hash123" in str(err)
        assert "42" in str(err)
        assert err.retry_after == 42
        assert err.key_hash == "hash123"
