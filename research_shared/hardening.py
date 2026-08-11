"""hardening.py — shared wiring for rate limiting, validation, and audit hardening.

Provides helpers to apply hardening middleware and create enhanced audit
loggers across all 6 MCP servers.  Each server calls apply_hardening()
at startup and build_audit_logger() per-request.

Usage in each MCP server.py:
    from research_shared.hardening import apply_hardening, build_audit_logger

    # After _auth definition:
    apply_hardening(app, _auth)

    # In each tool endpoint:
    logger = build_audit_logger(payload, request, _auth, "search-mcp")
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from research_shared.audit import AuditLogger
from research_shared.auth import AuthValidator
from research_shared.rate_limit import (
    SlidingWindowRateLimiter,
    create_rate_limit_middleware,
)
from research_shared.validation import create_payload_size_middleware

# ---------------------------------------------------------------------------
# apply_hardening — add rate limiting + payload size to an app
# ---------------------------------------------------------------------------

def apply_hardening(app: FastAPI, auth: AuthValidator) -> None:
    """Apply rate limiting and payload size middleware to *app*.

    Call once after creating the FastAPI app and auth.
    """
    # Add rate limiting middleware
    RateLimitMiddleware = create_rate_limit_middleware(
        SlidingWindowRateLimiter.from_env()
    )
    app.add_middleware(RateLimitMiddleware)

    # Add payload size middleware
    PayloadSizeMiddleware = create_payload_size_middleware()
    app.add_middleware(PayloadSizeMiddleware)


# ---------------------------------------------------------------------------
# build_audit_logger — create an audit logger with caller key
# ---------------------------------------------------------------------------

def build_audit_logger(
    payload: Any,
    request: Request,
    auth: AuthValidator,
    service_name: str,
) -> AuditLogger:
    """Create an AuditLogger with trace_id and caller_key_hash.

    Extracts the API key from request headers, hashes it, and passes
    it to the AuditLogger for audit trail completeness.
    """
    key = auth.extract_from_headers(dict(request.headers))
    key_hash = auth.hash_for_audit(key)
    return AuditLogger(
        trace_id=getattr(payload, "trace_id", None),
        service_name=service_name,
        caller_key_hash=key_hash,
    )


# ---------------------------------------------------------------------------
# build_audit_logger_from_kwargs — when payload is not a ResearchRequest
# ---------------------------------------------------------------------------

def build_audit_logger_from_kwargs(
    trace_id: str | None,
    request: Request,
    auth: AuthValidator,
    service_name: str,
) -> AuditLogger:
    """Create an AuditLogger from explicit trace_id (for non-standard endpoints)."""
    key = auth.extract_from_headers(dict(request.headers))
    key_hash = auth.hash_for_audit(key)
    return AuditLogger(
        trace_id=trace_id,
        service_name=service_name,
        caller_key_hash=key_hash,
    )
