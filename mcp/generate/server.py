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

from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.hardening import apply_hardening, build_audit_logger
from research_shared.lifespan import build_lifespan
from research_shared.llm import LLMError
from research_shared.seed_data import CONTENT_TYPES as SEED_CONTENT_TYPES

try:
    from research_shared.job_hunt_config import (
        DOMAIN_CONTENT_TYPES as JOB_HUNT_CONTENT_TYPES,
    )
except ImportError:  # domain not installed — graceful degradation
    JOB_HUNT_CONTENT_TYPES = []

# ---------------------------------------------------------------------------
# backend injection (must be before lifespan)
# ---------------------------------------------------------------------------

_db_pool: Any | None = None
_llm_client: Any | None = None


def set_db_pool(pool: Any | None) -> None:
    """Inject a DatabasePool for live knowledge-graph queries."""
    global _db_pool
    _db_pool = pool


def set_llm_client(client: Any | None) -> None:
    """Inject an LLMClient for live content generation."""
    global _llm_client
    _llm_client = client


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan(
    "generate-mcp",
    db_pool_ref=lambda: _db_pool,
    db_pool_setter=set_db_pool,
    llm_client_ref=lambda: _llm_client,
    llm_client_setter=set_llm_client,
)
app = FastAPI(title="generate-mcp", version="0.1.0", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)
apply_hardening(app, _auth)


def _require_auth(request: Request) -> None:
    if _auth.has_api_key:
        key = _auth.extract_from_headers(dict(request.headers))
        try:
            _auth.validate(key)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


# ---------------------------------------------------------------------------
# other injectors (not used by lifespan)
# ---------------------------------------------------------------------------

_self_extender: Any = None
_seed_loader: Any = None


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


# ---------------------------------------------------------------------------
# content type registry (from seed_data)
# ---------------------------------------------------------------------------

def _build_content_types_lookup() -> dict[str, dict[str, Any]]:
    """Build a name→definition lookup from seed_data.CONTENT_TYPES
    and any loaded domain config modules."""
    lookup: dict[str, dict[str, Any]] = {}
    for ct in SEED_CONTENT_TYPES:
        lookup[ct["name"]] = ct
    for ct in JOB_HUNT_CONTENT_TYPES:
        lookup[ct["name"]] = ct
    return lookup


_CONTENT_TYPES = _build_content_types_lookup()

# domain content type name sets for quick lookup
_JOB_HUNT_TYPE_NAMES = {ct["name"] for ct in JOB_HUNT_CONTENT_TYPES}


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    import logging as _logging
    _log = _logging.getLogger("saimon.health")
    db_ok = False
    llm_ok = False
    if _db_pool is not None:
        try:
            await _db_pool.fetch("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001
            _log.debug("generate-mcp health: DB not reachable", exc_info=True)
    if _llm_client is not None:
        try:
            await _llm_client.health_check()
            llm_ok = True
        except Exception:  # noqa: BLE001
            _log.debug("generate-mcp health: LLM not reachable", exc_info=True)
    return {
        "status": "ok",
        "service": "generate-mcp",
        "checks": {
            "database": "connected" if db_ok else "unavailable",
            "llm": "connected" if llm_ok else "unavailable",
        },
    }


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
    {
        "name": "generate_job_hunt_content",
        "description": "Generate job hunt domain content: resume, cover "
                       "letter, job match analysis, interview prep, or "
                       "salary benchmark.",
        "parameters": {
            "prompt": "str",
            "content_type": "str (one of: resume, cover_letter, job_match, "
                           "interview_prep, salary_benchmark)",
            "tone": "str (optional)",
        },
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

First, briefly outline your reasoning and evidence for each factual claim.
Then present the final content.

For any claim you are <90% confident about, prefix it with [LOW CONFIDENCE]
and explain why.

Do not invent statistics, dates, or names. Stick to claims you can support.

{sources_block}"""


def _format_sources_text(sources: list[Any]) -> str:
    """Format a list of SourceReference objects into a numbered text block.

    Each source is rendered with title, authors, and year when available.
    """
    if not sources:
        return ""

    parts = []
    for i, src in enumerate(sources, 1):
        title = getattr(src, "identifier", str(src))
        src_type = getattr(src, "type", "unknown")
        # Try to extract structured fields if the source has them
        src_title = getattr(src, "title", None)
        src_authors = getattr(src, "authors", None)
        src_year = getattr(src, "year", None)

        if src_title:
            title = src_title
        parts.append(f"{i}. {title} ({src_type})")
        if src_authors:
            parts[-1] += f" — {src_authors}"
        if src_year:
            parts[-1] += f", {src_year}"

    sources_text = "\n".join(parts)
    return (
        "Use ONLY the following sources. Do not introduce facts, statistics, "
        f"dates, or names not present in them:\n{sources_text}"
    )


async def _self_critique_pass(draft: str) -> str:
    """Run a self-critique pass on the generated draft.

    Feeds the draft back to the LLM with instructions to flag
    unverifiable claims and produce a final version.
    """
    review_prompt = (
        "Review the following draft for any unverifiable claims. "
        "Flag each with [UNVERIFIABLE] and explain why. "
        "Then produce the final version:\n\n"
        f"{draft}"
    )
    return await _llm_client.generate(review_prompt)  # type: ignore[union-attr]


async def _generate_via_llm(
    prompt: str,
    content_type: str,
    tone: str,
    ct_schema: dict[str, Any] | None,
    sources: list[Any] | None = None,
) -> str:
    """Generate content via the injected LLM client.

    When sources are provided, they are prepended to the prompt as a
    source-grounding constraint.  A two-turn self-critique pass reviews
    the draft for unverifiable claims and produces the final version.
    """
    extra = ""
    if ct_schema:
        opts = ct_schema.get("optional_params", [])
        if isinstance(opts, list) and opts and isinstance(opts[0], dict):
            extra = "- Options: " + ", ".join(
                p["name"] for p in opts if isinstance(p, dict)
            )

    sources_block = _format_sources_text(sources) if sources else ""

    llm_prompt = _GENERATE_PROMPT_TEMPLATE.format(
        content_type=content_type.replace("_", " "),
        prompt=prompt,
        tone=tone,
        extra_params=extra,
        sources_block=sources_block,
    )

    # Turn 1: generate draft
    draft = await _llm_client.generate(llm_prompt)  # type: ignore[union-attr]

    # Turn 2: self-critique pass
    try:
        final = await _self_critique_pass(draft)
        return final
    except Exception:  # noqa: BLE001 — self-critique is best-effort
        # If self-critique fails (e.g. LLM error), return the draft
        return draft


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

    logger = build_audit_logger(payload, request, _auth, "generate-mcp")
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
            content = await _generate_via_llm(
                prompt, content_type, tone, ct_schema,
                sources=payload.sources,
            )
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

    logger = build_audit_logger(payload, request, _auth, "generate-mcp")
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

    # Add domain content types
    for ct in JOB_HUNT_CONTENT_TYPES:
        types.append({
            "name": ct["name"],
            "description": ct["description"],
            "required_params": ct.get("required_params", []),
            "optional_params": ct.get("optional_params", []),
            "voice_profile": ct.get("voice_profile"),
            "domain": "job_hunt",
        })

    # Merge runtime-registered types from SelfExtender (if injected)
    if _self_extender is not None:
        try:
            registered = await _self_extender.list_registered_types()
            seed_names = {ct["name"] for ct in SEED_CONTENT_TYPES}
            domain_names = {ct["name"] for ct in JOB_HUNT_CONTENT_TYPES}
            known = seed_names | domain_names
            for rt in registered:
                if rt["name"] not in known:
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

    logger = build_audit_logger(payload, request, _auth, "generate-mcp")
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

    logger = build_audit_logger(payload, request, _auth, "generate-mcp")
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


# ---------------------------------------------------------------------------
# tool: generate_job_hunt_content
# ---------------------------------------------------------------------------


@app.post("/tools/generate_job_hunt_content")
async def generate_job_hunt_content(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    prompt = payload.parameters.get("prompt")
    if not prompt:
        return _error(payload.trace_id, "Parameter 'prompt' is required.")

    content_type = payload.content_type

    # Validate this is a job hunt domain type
    if content_type not in _JOB_HUNT_TYPE_NAMES:
        valid = ", ".join(sorted(_JOB_HUNT_TYPE_NAMES))
        return _error(
            payload.trace_id,
            f"'{content_type}' is not a job hunt content type. "
            f"Valid types: {valid}",
        )

    ct_schema = _CONTENT_TYPES.get(content_type)

    logger = build_audit_logger(payload, request, _auth, "generate-mcp")
    logger.log_request(
        content_type=content_type,
        tool="generate_job_hunt_content",
        prompt_length=len(prompt),
        sources_count=len(payload.sources),
    )

    # ── self-extend: try to register if somehow missing ──
    if ct_schema is None and _self_extender is not None:
        try:
            ct_schema = await _self_extender.ensure_type(content_type)
            logger.log_request(
                content_type=content_type,
                tool="self_extend",
                event="auto_registered",
            )
        except Exception:  # noqa: BLE001 — gracefully degrade
            ct_schema = None

    citations = [s.identifier for s in payload.sources] if payload.sources else []
    tone = payload.parameters.get("tone", "neutral")

    # ── try LLM backend ──
    if _llm_client is not None:
        try:
            content = await _generate_via_llm(
                prompt, content_type, tone, ct_schema,
                sources=payload.sources,
            )
            generated: dict[str, Any] = {
                "content": content,
                "content_type": content_type,
                "tone": tone,
                "word_count": len(content.split()),
                "backend": "llm",
                "domain": "job_hunt",
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

    # ── fallback ──
    fallback_content = (
        f"[{content_type.replace('_', ' ').title()}] "
        f"Prompt: {prompt}\n\n"
        f"(Job Hunt domain — LLM backend not available. "
        f"Set SAIMON_API_KEY and inject an LLMClient for full generation.)"
    )
    generated = {
        "content": fallback_content,
        "content_type": content_type,
        "tone": tone,
        "word_count": len(fallback_content.split()),
        "backend": "fallback",
        "domain": "job_hunt",
    }

    resp = _degraded(
        trace_id=payload.trace_id,
        data=generated,
        citations=citations,
    )
    logger.log_response(status=resp.status, citations_count=len(resp.citations or []))
    return resp
