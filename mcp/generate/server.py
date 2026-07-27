"""server.py — generate-mcp FastAPI application.

Provides LLM-powered content generation. Accepts a ResearchRequest
with content_type + parameters and returns generated content via
the ResearchResponse envelope.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse

# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

app = FastAPI(title="generate-mcp", version="0.1.0")

# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)


def _require_auth(request: Request) -> None:
    if _auth.has_api_key:
        key = _auth.extract_from_headers(dict(request.headers))
        try:
            _auth.validate(key)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


# ---------------------------------------------------------------------------
# content type registry
# ---------------------------------------------------------------------------

_CONTENT_TYPES: dict[str, dict[str, Any]] = {
    "blog_post": {
        "name": "blog_post",
        "description": "A long-form blog article with introduction, body, and conclusion.",
        "required_params": ["prompt"],
        "optional_params": ["tone", "max_length", "audience"],
    },
    "summary": {
        "name": "summary",
        "description": "A concise summary of source material.",
        "required_params": ["prompt"],
        "optional_params": ["max_length", "style"],
    },
    "research_note": {
        "name": "research_note",
        "description": "A structured research note with citations.",
        "required_params": ["prompt"],
        "optional_params": ["tone", "depth", "format"],
    },
    "social_post": {
        "name": "social_post",
        "description": "A short-form social media post.",
        "required_params": ["prompt"],
        "optional_params": ["platform", "tone", "max_length"],
    },
    "email_draft": {
        "name": "email_draft",
        "description": "A polished email draft.",
        "required_params": ["prompt"],
        "optional_params": ["tone", "recipient_role"],
    },
}


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "generate-mcp"}


# ---------------------------------------------------------------------------
# tool listing
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "generate_content",
        "description": "Generate content using the LLM for a given content type.",
        "parameters": {"prompt": "str", "tone": "str (optional)", "content_type": "str"},
    },
    {
        "name": "list_content_types",
        "description": "List all registered content types with their schemas.",
        "parameters": {},
    },
    {
        "name": "get_content_type_schema",
        "description": "Get the parameter schema for a specific content type.",
        "parameters": {"type_name": "str"},
    },
]


@app.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    _require_auth(request)
    return {"tools": _TOOLS}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ok(
    trace_id: str,
    data: Any = None,
    citations: list[str] | None = None,
) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id, status="success", data=data, citations=citations
    )


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(trace_id=trace_id, status="error", errors=[message])


# ---------------------------------------------------------------------------
# tool: generate_content
# ---------------------------------------------------------------------------

@app.post("/tools/generate_content")
async def generate_content(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    prompt = payload.parameters.get("prompt")
    if not prompt:
        return _error(payload.trace_id, "Parameter 'prompt' is required.")

    content_type = payload.content_type
    ct_schema = _CONTENT_TYPES.get(content_type)

    logger = AuditLogger(trace_id=payload.trace_id, service_name="generate-mcp")
    logger.log_request(
        content_type=content_type,
        tool="generate_content",
        prompt_length=len(prompt),
        sources_count=len(payload.sources),
    )

    # Derive citations from provided sources
    citations = [s.identifier for s in payload.sources] if payload.sources else []

    # Placeholder generation — in production this calls the LLM via research_shared.llm
    tone = payload.parameters.get("tone", "neutral")
    generated = {
        "content": f"[Generated {content_type}] Prompt: {prompt}\n\n"
        f"This is a placeholder response. In production, this would be "
        f"generated by DeepSeek via research_shared.llm.LLMClient.",
        "content_type": content_type,
        "tone": tone,
        "word_count": 42,
        "schema": ct_schema,
    }

    resp = _ok(
        trace_id=payload.trace_id,
        data=generated,
        citations=citations,
    )
    logger.log_response(status=resp.status, citations_count=len(resp.citations or []))
    return resp


# ---------------------------------------------------------------------------
# tool: list_content_types
# ---------------------------------------------------------------------------

@app.post("/tools/list_content_types")
async def list_content_types(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    logger = AuditLogger(trace_id=payload.trace_id, service_name="generate-mcp")
    logger.log_request(content_type=payload.content_type, tool="list_content_types")

    types = [
        {
            "name": name,
            "description": schema["description"],
            "required_params": schema["required_params"],
        }
        for name, schema in _CONTENT_TYPES.items()
    ]

    resp = _ok(trace_id=payload.trace_id, data={"types": types})
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: get_content_type_schema
# ---------------------------------------------------------------------------

@app.post("/tools/get_content_type_schema")
async def get_content_type_schema(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    type_name = payload.parameters.get("type_name")
    if not type_name:
        return _error(payload.trace_id, "Parameter 'type_name' is required.")

    logger = AuditLogger(trace_id=payload.trace_id, service_name="generate-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="get_content_type_schema",
        type_name=type_name,
    )

    schema = _CONTENT_TYPES.get(type_name)
    if schema is None:
        return _error(
            payload.trace_id,
            f"Unknown content type: {type_name!r}. "
            "Use list_content_types to see available types.",
        )

    resp = _ok(trace_id=payload.trace_id, data=schema)
    logger.log_response(status=resp.status)
    return resp
