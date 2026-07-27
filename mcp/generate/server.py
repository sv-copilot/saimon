"""server.py — generate-mcp FastAPI application.

Provides LLM-powered content generation. Accepts a ResearchRequest
with content_type + parameters and returns generated content via
the ResearchResponse envelope.

Supports dependency injection of an LLMClient via set_llm_client().
When an LLM is injected, generate_content uses it for real generation.
When not injected, the MCP degrades gracefully with fallback responses.

Supports runtime self-extension: when a content type is unknown and a
SelfExtender is injected, the MCP researches and auto-registers it.
Supports DB re-seeding via SeedLoader injection.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.llm import LLMClient, LLMError
from research_shared.seed_data import CONTENT_TYPES as SEED_CONTENT_TYPES

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
# backend injection
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None
_self_extender: Any = None
_seed_loader: Any = None
_db_pool: Any = None


def set_llm_client(client: LLMClient | None) -> None:
    """Inject an LLMClient backend for production use.

    When set, generate_content uses the LLM for real generation.
    When None (default), the MCP degrades gracefully with fallbacks.
    """
    global _llm_client
    _llm_client = client


def set_self_extender(extender: Any | None) -> None:
    """Inject a SelfExtender for runtime content type registration.

    When set, unknown content types trigger research → auto-register.
    When None (default), unknown types return an error.
    """
    global _self_extender
    _self_extender = extender


def set_seed_loader(loader: Any | None) -> None:
    """Inject a SeedLoader for DB re-seeding.

    When set, seed_content_types loads canonical seed data into the DB.
    When None (default), the tool degrades gracefully.
    """
    global _seed_loader
    _seed_loader = loader


def set_db_pool(pool: Any | None) -> None:
    """Inject a DatabasePool for backend queries.

    When set, used by SelfExtender and SeedLoader for DB access.
    When None (default), DB-backed features degrade gracefully.
    """
    global _db_pool
    _db_pool = pool


# ---------------------------------------------------------------------------
# content type registry (from seed_data)
# ---------------------------------------------------------------------------

def _build_content_types_lookup() -> dict[str, dict[str, Any]]:
    """Build a name→definition lookup from seed_data.CONTENT_TYPES."""
    lookup: dict[str, dict[str, Any]] = {}
    for ct in SEED_CONTENT_TYPES:
        lookup[ct["name"]] = ct
    return lookup


_CONTENT_TYPES = _build_content_types_lookup()


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
    {
        "name": "seed_content_types",
        "description": "Re-seed the database with canonical content types, "
                       "voice profiles, and seed requests.",
        "parameters": {},
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


def _degraded(trace_id: str, data: Any = None, citations: list[str] | None = None) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id, status="degraded", data=data, citations=citations,
    )


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(trace_id=trace_id, status="error", errors=[message])


# ---------------------------------------------------------------------------
# LLM generation helper
# ---------------------------------------------------------------------------

_GENERATE_PROMPT_TEMPLATE = """You are a content generation assistant.

Generate a {content_type} with the following parameters:
- Prompt: {prompt}
- Tone: {tone}
{extra_params}

Return ONLY the generated content — no preamble, no meta-commentary."""


async def _generate_via_llm(
    prompt: str,
    content_type: str,
    tone: str,
    ct_schema: dict[str, Any] | None,
) -> str:
    """Generate content via the injected LLM client."""
    extra = ""
    if ct_schema:
        opts = ct_schema.get("optional_params", [])
        if isinstance(opts, list) and opts and isinstance(opts[0], dict):
            extra = "- Options: " + ", ".join(
                p["name"] for p in opts if isinstance(p, dict)
            )
    llm_prompt = _GENERATE_PROMPT_TEMPLATE.format(
        content_type=content_type.replace("_", " "),
        prompt=prompt,
        tone=tone,
        extra_params=extra,
    )
    return await _llm_client.generate(llm_prompt)  # type: ignore[union-attr]


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

    # ── self-extend: try to register unknown types ──
    if ct_schema is None and _self_extender is not None:
        try:
            ct_schema = await _self_extender.ensure_type(content_type)
            logger.log_request(
                content_type=content_type,
                tool="self_extend",
                event="auto_registered",
            )
        except Exception:  # noqa: BLE001 — graceful degradation on self-extend failure
            # Self-extend failed — continue with fallback below
            ct_schema = None

    citations = [s.identifier for s in payload.sources] if payload.sources else []
    tone = payload.parameters.get("tone", "neutral")

    # ── try LLM backend ──
    if _llm_client is not None:
        try:
            content = await _generate_via_llm(prompt, content_type, tone, ct_schema)
            generated: dict[str, Any] = {
                "content": content,
                "content_type": content_type,
                "tone": tone,
                "word_count": len(content.split()),
                "backend": "llm",
            }
            resp = _ok(
                trace_id=payload.trace_id,
                data=generated,
                citations=citations,
            )
            logger.log_response(
                status=resp.status, citations_count=len(resp.citations or [])
            )
            return resp
        except LLMError as exc:
            logger.log_response(status="error")
            return _error(payload.trace_id, f"LLM generation failed: {exc}")
        except NotImplementedError:
            pass  # fall through to fallback

    # ── fallback (no LLM, or LLM not implemented) ──
    fallback_content = (
        f"[{content_type.replace('_', ' ').title()}] "
        f"Prompt: {prompt}\n\n"
        f"(LLM backend not available — degraded mode. "
        f"Set SAIMON_API_KEY and inject an LLMClient for full generation.)"
    )
    generated = {
        "content": fallback_content,
        "content_type": content_type,
        "tone": tone,
        "word_count": len(fallback_content.split()),
        "backend": "fallback",
    }

    resp = _degraded(
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

    # Start with seed data types
    types = [
        {
            "name": ct["name"],
            "description": ct["description"],
            "required_params": ct.get("required_params", []),
            "optional_params": ct.get("optional_params", []),
            "voice_profile": ct.get("voice_profile"),
        }
        for ct in SEED_CONTENT_TYPES
    ]

    # Merge runtime-registered types from SelfExtender (if injected)
    if _self_extender is not None:
        try:
            registered = await _self_extender.list_registered_types()
            seed_names = {ct["name"] for ct in SEED_CONTENT_TYPES}
            for rt in registered:
                if rt["name"] not in seed_names:
                    types.append(rt)
        except Exception:  # noqa: BLE001, S110 — degrade gracefully if registry unavailable
            pass

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

    # Check seed data first, then try registry via SelfExtender
    schema = _CONTENT_TYPES.get(type_name)

    if schema is None and _self_extender is not None:
        try:
            schema = await _self_extender.ensure_type(type_name)
        except Exception:  # noqa: BLE001, S110 — degrade gracefully on self-extend failure
            pass

    if schema is None:
        return _error(
            payload.trace_id,
            f"Unknown content type: {type_name!r}. "
            "Use list_content_types to see available types.",
        )

    resp = _ok(trace_id=payload.trace_id, data=schema)
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: seed_content_types
# ---------------------------------------------------------------------------

@app.post("/tools/seed_content_types")
async def seed_content_types(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    logger = AuditLogger(trace_id=payload.trace_id, service_name="generate-mcp")
    logger.log_request(content_type=payload.content_type, tool="seed_content_types")

    if _seed_loader is None:
        counts = {
            "content_types": len(SEED_CONTENT_TYPES),
            "voice_profiles": 5,  # from seed_data.py
            "seed_requests": 15,  # from seed_data.py
        }
        resp = _degraded(
            trace_id=payload.trace_id,
            data={
                "message": "Seed loader not injected — returning seed data counts only.",
                "counts": counts,
            },
        )
        logger.log_response(status=resp.status)
        return resp

    try:
        result = await _seed_loader.load_all()
        resp = _ok(trace_id=payload.trace_id, data=result)
        logger.log_response(status=resp.status)
        return resp
    except Exception as exc:  # noqa: BLE001 — catch-all for seed failures
        logger.log_response(status="error")
        return _error(payload.trace_id, f"Seed failed: {exc}")
