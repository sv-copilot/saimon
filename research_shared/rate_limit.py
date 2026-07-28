"""rate_limit.py — per-API-key rate limiting with sliding window.

Provides RateLimiter middleware for FastAPI that enforces configurable
per-key rate limits.  Uses a sliding-window algorithm with in-memory
storage (suitable for single-process deployments).

Configuration:
    SAIMON_RATE_LIMIT_MAX — max requests per window (default 100)
    SAIMON_RATE_LIMIT_WINDOW — window size in seconds (default 60)

When a key exceeds the limit, the response returns 429 with an
Envelope-compatible error body.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# RateLimitExceededError — raised when limit is hit
# ---------------------------------------------------------------------------

class RateLimitExceededError(Exception):
    """Raised when a caller exceeds their rate limit."""

    def __init__(self, key_hash: str, retry_after: int) -> None:
        self.key_hash = key_hash
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for key {key_hash}. Retry after {retry_after}s."
        )


# ---------------------------------------------------------------------------
# SlidingWindowRateLimiter
# ---------------------------------------------------------------------------

class SlidingWindowRateLimiter:
    """Per-API-key sliding-window rate limiter.

    Tracks request timestamps per key in a sliding window.  When the
    count exceeds *max_requests* within *window_seconds*, subsequent
    requests are rejected until the window slides forward.

    Thread-safe for asyncio (single-threaded async) but NOT for
    multi-threaded use.  For multi-worker deployments, replace with
    Redis-backed storage.
    """

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: float = 60.0,
        header_name: str = "X-Saimon-API-Key",
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.header_name = header_name
        self._buckets: dict[str, list[float]] = defaultdict(list)

    @classmethod
    def from_env(cls) -> SlidingWindowRateLimiter:
        """Build from SAIMON_RATE_LIMIT_* environment variables."""
        return cls(
            max_requests=int(os.getenv("SAIMON_RATE_LIMIT_MAX", "100")),
            window_seconds=float(os.getenv("SAIMON_RATE_LIMIT_WINDOW", "60")),
        )

    def _extract_key(self, request: Request) -> str:
        """Extract the API key from request headers for bucketing."""
        for name, value in request.headers.items():
            if name.lower() == self.header_name.lower():
                return value
        return "anonymous"

    def _clean_window(self, key: str, now: float) -> None:
        """Remove timestamps outside the current sliding window."""
        cutoff = now - self.window_seconds
        bucket = self._buckets[key]
        # Remove expired entries
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)

    def check(self, request: Request) -> int | None:
        """Check the rate limit for *request*.

        Returns:
            None if the request is within limits.
            retry_after (int seconds) if the limit is exceeded.
        """
        key = self._extract_key(request)
        now = time.monotonic()

        self._clean_window(key, now)
        bucket = self._buckets[key]

        if len(bucket) >= self.max_requests:
            # Calculate how long until the oldest request expires
            oldest = bucket[0] if bucket else now
            retry_after = max(1, int(self.window_seconds - (now - oldest)))
            return retry_after

        # Record this request
        bucket.append(now)
        return None

    def reset(self, key: str | None = None) -> None:
        """Reset the rate limit bucket(s).

        If *key* is None, reset all buckets.
        """
        if key is None:
            self._buckets.clear()
        else:
            self._buckets.pop(key, None)

    @property
    def bucket_count(self) -> int:
        """Number of distinct keys being tracked (for testing)."""
        return len(self._buckets)


# ---------------------------------------------------------------------------
# Envelope-compatible 429 response
# ---------------------------------------------------------------------------

def rate_limit_exceeded_response(
    trace_id: str = "unknown",
    retry_after: int = 60,
) -> JSONResponse:
    """Return a 429 response matching the Envelope format."""
    return JSONResponse(
        status_code=429,
        content={
            "trace_id": trace_id,
            "status": "error",
            "errors": [
                f"Rate limit exceeded. Retry after {retry_after} seconds."
            ],
            "data": None,
            "citations": None,
        },
        headers={"Retry-After": str(retry_after)},
    )


# ---------------------------------------------------------------------------
# FastAPI middleware factory
# ---------------------------------------------------------------------------

def create_rate_limit_middleware(
    rate_limiter: SlidingWindowRateLimiter,
) -> Any:
    """Create a raw ASGI middleware that applies rate limiting.

    This wraps the rate limiter as an ASGI middleware so it runs
    before any route handler.  The /health endpoint is exempt.

    Usage:
        app.add_middleware(
            create_rate_limit_middleware(rate_limiter),
        )
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next: Any) -> Any:
            # Skip rate limiting for health checks
            if request.url.path == "/health":
                return await call_next(request)

            # Check rate limit
            retry_after = rate_limiter.check(request)
            if retry_after is not None:
                trace_id = "unknown"
                try:
                    body = await request.body()
                    import json
                    data = json.loads(body) if body else {}
                    trace_id = data.get("trace_id", "unknown")
                except Exception:
                    pass
                return rate_limit_exceeded_response(
                    trace_id=trace_id, retry_after=retry_after
                )

            return await call_next(request)

    return RateLimitMiddleware
