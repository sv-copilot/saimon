"""Tests for SAIMON-RATE-LIMIT (#48) — rate limiting + circuit breaker.

Covers: SlidingWindowRateLimiter (per-key quotas, 429 responses),
CircuitBreaker (CLOSED→OPEN→HALF_OPEN state machine),
rate limit middleware enforcement.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_shared.rate_limit import (
    SlidingWindowRateLimiter,
    RateLimitExceededError,
    create_rate_limit_middleware,
    rate_limit_exceeded_response,
)
from research_shared.resilience import CircuitBreaker, CircuitState


# ---------------------------------------------------------------------------
# SlidingWindowRateLimiter tests
# ---------------------------------------------------------------------------

class TestSlidingWindowRateLimiter:
    """Tests for the per-API-key sliding window rate limiter."""

    def test_allows_within_limit(self):
        """Requests within the limit should be allowed."""
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)

        for _ in range(5):
            request = _make_request(key="sk-test-1")
            retry_after = limiter.check(request)
            assert retry_after is None, "Request within limit should be allowed"

    def test_blocks_after_limit(self):
        """Requests exceeding the limit should return retry_after."""
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)

        for _ in range(3):
            request = _make_request(key="sk-test-2")
            assert limiter.check(request) is None

        # 4th request should be blocked
        request = _make_request(key="sk-test-2")
        retry_after = limiter.check(request)
        assert retry_after is not None, "Request over limit should be blocked"
        assert retry_after > 0

    def test_tracks_keys_independently(self):
        """Different API keys have independent quotas."""
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)

        # Exhaust key-1
        for _ in range(2):
            assert limiter.check(_make_request(key="sk-key-1")) is None
        assert limiter.check(_make_request(key="sk-key-1")) is not None

        # key-2 should still be allowed
        assert limiter.check(_make_request(key="sk-key-2")) is None

    def test_reset_clears_buckets(self):
        """reset() should clear tracked buckets."""
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)

        limiter.check(_make_request(key="sk-test-3"))
        assert limiter.bucket_count == 1

        limiter.reset()
        assert limiter.bucket_count == 0

        # Should be allowed again after reset
        assert limiter.check(_make_request(key="sk-test-3")) is None

    def test_anonymous_key_when_no_header(self):
        """Requests without API key header use 'anonymous' bucket."""
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
        request = _make_request(key=None)

        assert limiter.check(request) is None
        assert limiter.check(request) is not None

    def test_from_env_defaults(self):
        """from_env() should use defaults when env vars are unset."""
        limiter = SlidingWindowRateLimiter.from_env()
        assert limiter.max_requests == 100
        assert limiter.window_seconds == 60


# ---------------------------------------------------------------------------
# RateLimitExceededError tests
# ---------------------------------------------------------------------------

class TestRateLimitExceededError:
    """Tests for the rate limit exceeded error."""

    def test_error_contains_key_and_retry(self):
        """Error should include key hash and retry_after seconds."""
        err = RateLimitExceededError(key_hash="abc123", retry_after=30)
        assert "abc123" in str(err)
        assert "30" in str(err)
        assert err.key_hash == "abc123"
        assert err.retry_after == 30


# ---------------------------------------------------------------------------
# 429 response tests
# ---------------------------------------------------------------------------

class TestRateLimitResponse:
    """Tests for the envelope-compatible 429 response."""

    def test_response_status_code(self):
        """Should return HTTP 429."""
        resp = rate_limit_exceeded_response(trace_id="test-1", retry_after=60)
        assert resp.status_code == 429

    def test_response_contains_retry_after_header(self):
        """Should include Retry-After header."""
        resp = rate_limit_exceeded_response(trace_id="test-1", retry_after=45)
        assert resp.headers["Retry-After"] == "45"

    def test_response_envelope_format(self):
        """Should follow the Envelope format."""
        import json
        resp = rate_limit_exceeded_response(trace_id="test-2", retry_after=30)
        body = json.loads(resp.body)
        assert body["trace_id"] == "test-2"
        assert body["status"] == "error"
        assert len(body["errors"]) > 0


# ---------------------------------------------------------------------------
# Middleware tests
# ---------------------------------------------------------------------------

class TestRateLimitMiddleware:
    """Tests for the FastAPI rate limit middleware."""

    def test_middleware_allows_under_limit(self):
        """Middleware should allow requests within the rate limit."""
        limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60)
        middleware_cls = create_rate_limit_middleware(limiter)

        app = FastAPI()
        app.add_middleware(middleware_cls)

        @app.post("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.post(
            "/test",
            json={"trace_id": "mw-1"},
            headers={"X-Saimon-API-Key": "sk-mw-1"},
        )
        assert resp.status_code == 200

    def test_middleware_blocks_over_limit(self):
        """Middleware should return 429 when limit exceeded."""
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
        middleware_cls = create_rate_limit_middleware(limiter)

        app = FastAPI()
        app.add_middleware(middleware_cls)

        @app.post("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        headers = {"X-Saimon-API-Key": "sk-mw-2"}

        # First 2 should pass
        for _ in range(2):
            resp = client.post("/test", json={"trace_id": "mw-2"}, headers=headers)
            assert resp.status_code == 200

        # 3rd should be blocked
        resp = client.post("/test", json={"trace_id": "mw-2"}, headers=headers)
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_middleware_exempts_health(self):
        """Middleware should not rate-limit the /health endpoint."""
        limiter = SlidingWindowRateLimiter(max_requests=0, window_seconds=60)
        middleware_cls = create_rate_limit_middleware(limiter)

        app = FastAPI()
        app.add_middleware(middleware_cls)

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Tests for the LLM circuit breaker state machine."""

    def test_initial_state_is_closed(self):
        """Circuit breaker should start CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        assert cb.state == CircuitState.CLOSED
        assert cb.allows() is True

    def test_opens_after_failure_threshold(self):
        """Circuit should OPEN after N consecutive failures."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

        for _ in range(3):
            cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert cb.allows() is False

    def test_half_open_after_recovery_timeout(self):
        """Circuit should go HALF_OPEN after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)

        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.02)

        # First probe should be allowed (HALF_OPEN)
        assert cb.allows() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_recovers_to_closed_after_success(self):
        """HALF_OPEN → success → CLOSED."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)

        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        cb.allows()  # Transition to HALF_OPEN
        cb.record_success()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_goes_back_to_open_on_half_open_failure(self):
        """HALF_OPEN → failure → OPEN."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)

        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        cb.allows()  # Transition to HALF_OPEN

        # Fail while in HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allows() is False

    def test_success_resets_failure_count(self):
        """Success before threshold should reset count."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

        cb.record_failure()
        cb.record_failure()
        cb.record_success()

        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(key: str | None) -> MagicMock:
    """Build a mock FastAPI Request with an optional API key header."""
    request = MagicMock()
    request.url.path = "/test"
    if key is not None:
        request.headers.items.return_value = [("x-saimon-api-key", key)]
    else:
        request.headers.items.return_value = []
    return request
