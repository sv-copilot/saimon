"""envelope.py — typed request/response contracts for MCP communication.

Every MCP call flows through a ResearchRequest → ResearchResponse cycle.
These models provide schema validation, serialisation, and the shared
vocabulary all six MCPs depend on.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# ErrorCode
# ---------------------------------------------------------------------------

class ErrorCode(str, Enum):
    """Standardised error codes shared across all MCPs."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    LLM_ERROR = "LLM_ERROR"
    DB_ERROR = "DB_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# SourceReference
# ---------------------------------------------------------------------------

class SourceReference(BaseModel):
    """A citation to a source used when generating a response.

    Sources may be knowledge-graph nodes, web pages, uploaded documents,
    or any other referenceable content.
    """

    type: str = Field(..., description="Source kind: knowledge_graph, web_page, document, etc.")
    identifier: str = Field(..., description="Unique identifier within the source type.")
    relevance_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional relevance score 0.0–1.0.",
    )


# ---------------------------------------------------------------------------
# ResearchRequest
# ---------------------------------------------------------------------------

class ResearchRequest(BaseModel):
    """An inbound request from an agent or user.

    Carries a trace_id for end-to-end observability, the requested
    content_type, optional parameters, and optional source references.
    """

    trace_id: str = Field(..., description="UUID v4 trace identifier.")
    content_type: str = Field(..., min_length=1, description="Requested content type.")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value parameters for the request.",
    )
    sources: list[SourceReference] = Field(
        default_factory=list,
        description="Optional source references to ground the response.",
    )

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except (ValueError, AttributeError):
            raise ValueError(f"trace_id must be a valid UUID, got: {v!r}")
        return v


# ---------------------------------------------------------------------------
# ResearchResponse
# ---------------------------------------------------------------------------

class ResearchResponse(BaseModel):
    """The standard response envelope returned by every MCP.

    status is one of 'success', 'error', or 'degraded'.  A success
    response carries data + citations.  An error response carries
    errors.  A degraded response carries both (partial success).
    """

    trace_id: str = Field(..., description="Echoes the request trace_id.")
    status: str = Field(..., description="One of: success, error, degraded.")
    data: Any | None = Field(default=None, description="Response payload.")
    errors: list[str] | None = Field(default=None, description="Error messages if any.")
    citations: list[str] | None = Field(
        default=None,
        description="URLs or identifiers of cited sources.",
    )

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in ("success", "error", "degraded"):
            raise ValueError(
                f"status must be 'success', 'error', or 'degraded', got: {v!r}"
            )
        return v
