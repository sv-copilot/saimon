"""validation.py — input validation and payload hardening.

Provides validators for:
- Maximum payload size (configurable via SAIMON_MAX_PAYLOAD_BYTES)
- String length limits on all user-supplied inputs
- Content type validation against registered types (whitelist)

Configuration:
    SAIMON_MAX_PAYLOAD_BYTES — max request body size (default 1MB)
    SAIMON_MAX_STRING_LENGTH — max length for any string input (default 10000)
    SAIMON_MAX_QUERY_LENGTH — max length for search queries (default 1000)
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when input validation fails."""


# ---------------------------------------------------------------------------
# limits
# ---------------------------------------------------------------------------

_max_payload_bytes = int(os.getenv("SAIMON_MAX_PAYLOAD_BYTES", str(1024 * 1024)))
_max_string_length = int(os.getenv("SAIMON_MAX_STRING_LENGTH", "10000"))
_max_query_length = int(os.getenv("SAIMON_MAX_QUERY_LENGTH", "1000"))


def get_max_payload_bytes() -> int:
    """Return the configured max payload size in bytes."""
    return _max_payload_bytes


def get_max_string_length() -> int:
    """Return the configured max string length."""
    return _max_string_length


def get_max_query_length() -> int:
    """Return the configured max query length."""
    return _max_query_length


# ---------------------------------------------------------------------------
# string validation
# ---------------------------------------------------------------------------

def validate_string_length(
    value: str,
    max_length: int | None = None,
    field_name: str = "value",
) -> str:
    """Validate that *value* does not exceed *max_length*.

    Returns *value* if valid, raises ValidationError otherwise.
    """
    limit = max_length if max_length is not None else _max_string_length
    if len(value) > limit:
        raise ValidationError(
            f"Field '{field_name}' exceeds maximum length of {limit} "
            f"(got {len(value)})."
        )
    return value


def validate_query(query: str) -> str:
    """Validate a search query string against the query length limit."""
    return validate_string_length(query, max_length=_max_query_length, field_name="query")


# ---------------------------------------------------------------------------
# content type validation (whitelist)
# ---------------------------------------------------------------------------

_VALID_CONTENT_TYPES: set[str] = set()


def set_valid_content_types(types: set[str]) -> None:
    """Register the set of valid content types (whitelist).

    Called at startup from seed_data or DB.
    """
    global _VALID_CONTENT_TYPES
    _VALID_CONTENT_TYPES = types


def get_valid_content_types() -> set[str]:
    """Return the current whitelist of valid content types."""
    return _VALID_CONTENT_TYPES


def validate_content_type(content_type: str) -> str:
    """Validate that *content_type* is in the registered whitelist.

    If the whitelist is empty (not yet loaded), all types are allowed.
    Returns *content_type* if valid, raises ValidationError otherwise.
    """
    if not _VALID_CONTENT_TYPES:
        # Whitelist not loaded yet — allow all (degraded mode)
        return content_type

    if content_type not in _VALID_CONTENT_TYPES:
        raise ValidationError(
            f"Unknown content type: {content_type!r}. "
            f"Valid types: {', '.join(sorted(_VALID_CONTENT_TYPES))}"
        )
    return content_type


# ---------------------------------------------------------------------------
# payload size middleware
# ---------------------------------------------------------------------------

def create_payload_size_middleware() -> Any:
    """Create ASGI middleware that enforces max payload size.

    Returns 413 Payload Too Large when the request body exceeds
    SAIMON_MAX_PAYLOAD_BYTES.
    """
    from starlette.middleware.base import BaseHTTPMiddleware

    class PayloadSizeMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Any:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    length = int(content_length)
                    if length > _max_payload_bytes:
                        return JSONResponse(
                            status_code=413,
                            content={
                                "trace_id": "unknown",
                                "status": "error",
                                "errors": [
                                    f"Payload too large. "
                                    f"Max: {_max_payload_bytes} bytes, "
                                    f"got: {length} bytes."
                                ],
                                "data": None,
                                "citations": None,
                            },
                        )
                except (ValueError, TypeError):
                    pass
            return await call_next(request)

    return PayloadSizeMiddleware


# ---------------------------------------------------------------------------
# validation error response (Envelope-compatible)
# ---------------------------------------------------------------------------

def validation_error_response(
    trace_id: str,
    message: str,
) -> JSONResponse:
    """Return a 422 response matching the Envelope format."""
    return JSONResponse(
        status_code=422,
        content={
            "trace_id": trace_id,
            "status": "error",
            "errors": [message],
            "data": None,
            "citations": None,
        },
    )
