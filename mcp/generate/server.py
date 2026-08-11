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
    kg_nodes = 0
    if _db_pool is not None and db_ok:
        try:
            row = await _db_pool.fetch("SELECT count(*) as cnt FROM knowledge_graph_nodes")
            kg_nodes = row[0]["cnt"] if row else 0
        except Exception:  # noqa: BLE001
            _log.debug("generate-mcp health: KG node count query failed", exc_info=True)
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
            "kg_nodes": kg_nodes,
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
        "name": "generate_verified",
        "description": "Generate content with full verification pipeline: "
                       "generate → evaluate → extract claims → verify each → "
                       "annotate. Output includes [VERIFIED ✓] / [UNVERIFIABLE ⚠] "
                       "markers with evidence.",
        "parameters": {
            "prompt": "str",
            "content_type": "str",
            "tone": "str (optional)",
        },
    },
    {
        "name": "self_seed",
        "description": "Generate content from pending seed_requests and persist "
                       "to the knowledge graph. Idempotent — only processes "
                       "rows with status='pending'.",
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

_DIRECT_PROMPT_TEMPLATE = """You are a content generation assistant.

Generate a {content_type} with the following parameters:
- Prompt: {prompt}
- Tone: {tone}
{extra_params}

Produce the final content directly. Do not include meta-commentary,
review headers, or self-critique. Write as if you are the author.

Do not invent statistics, dates, or names. Stick to claims you can support.

{sources_block}"""


_VERIFIED_PROMPT_TEMPLATE = """You are a content generation assistant.

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


# ---------------------------------------------------------------------------
# quality gates (ported from legacy research-service)
# ---------------------------------------------------------------------------

# Patterns that indicate meta-commentary / instructional wrapping
_INSTRUCTIONAL_META_PATTERNS = [
    r"review of unverifiable claims",
    r"here is the (review|revised|final) version",
    r"i have reviewed the (draft|content|output)",
    r"below is (my|the) (analysis|review|evaluation)",
    r"let me (review|analyze|evaluate|assess) the",
    r"i('ve| have) (reviewed|analyzed|evaluated|checked)",
    r"after reviewing the (draft|content|above)",
    r"the following (is|are) my (observations|notes|findings)",
    r"i('ll| will) now (review|analyze|break down)",
    r"here('s| is) what i (found|discovered|noticed)",
    r"let('s| us) (examine|look at|consider|review)",
    r"summary of (key )?(findings|claims|issues)",
    r"based on (my|the) (review|analysis|assessment)",
    r"i can (see|identify|spot|detect) (several|a few|some)",
    r"the draft (contains|has|includes|shows)",
]

# Patterns that reveal AI voice / templated language
_VOICE_RISK_PATTERNS = [
    r"\bas an ai\b",
    r"\bhere is a draft\b",
    r"\bhere are (some|a few)\b",
    r"\bi hope this\b",
    r"\bplease note that\b",
]

# Patterns indicating broken or fabricated attribution
_BROKEN_ATTRIBUTION_PATTERNS = [
    r"according to \[\]",
    r"\(Source: \s*\)",
    r"\[citation needed\]",
    r"\(n\.d\.\)",  # no-date without source
]

# Generic template filler patterns
_GENERIC_TEMPLATE_PATTERNS = [
    r"\bthis (blog post|article|paper|report) (will|aims to|seeks to)\b",
    r"\bin (today|this)('s)? (digital|modern|fast-paced|ever-changing) (world|era|landscape)\b",
    r"\bit is (important|crucial|essential|vital|critical) to (understand|note|consider|recognize)\b",
    r"\bin conclusion[,:]\s",
    r"\bas we (have|'ve) (seen|discussed|explored)\b",
    r"\b(to )?summarize[,:]\s",
    r"\bneedless to say\b",
    r"\bgoes without saying\b",
    r"\bat the end of the day\b",
    r"\bthink outside the box\b",
    r"\bgame.changer\b",
    r"\bparadigm shift\b",
    r"\bunprecedented\b",
    r"\bin these uncertain times\b",
]

# Forbidden phrases — reject outright
_DEFAULT_FORBIDDEN_PHRASES = [
    "as an AI language model",
    "as an AI, I",
    "as a language model",
    "I am an AI",
]


def _quality_gate_check(
    text: str,
    content_type: str,
    forbidden_phrases: list[str] | None = None,
) -> dict[str, Any]:
    """Run post-generation quality gates against generated content.

    Returns {passed: bool, reason: str|None}.
    Rejects content that contains meta-commentary, voice-risk patterns,
    broken attribution, or forbidden phrases.
    """
    import re

    text_lower = text.lower()
    forbidden = forbidden_phrases or _DEFAULT_FORBIDDEN_PHRASES

    # ── forbidden phrases ──
    for phrase in forbidden:
        if phrase.lower() in text_lower:
            return {"passed": False, "reason": f"Forbidden phrase detected: {phrase!r}"}

    # ── voice risk patterns (reject immediately) ──
    for pattern in _VOICE_RISK_PATTERNS:
        if re.search(pattern, text_lower):
            return {"passed": False, "reason": f"Voice risk pattern matched: {pattern!r}"}

    # ── broken attribution ──
    for pattern in _BROKEN_ATTRIBUTION_PATTERNS:
        if re.search(pattern, text):
            return {"passed": False, "reason": f"Broken attribution pattern matched: {pattern!r}"}

    # ── instructional meta (reject immediately for direct generation) ──
    meta_hits = []
    for pattern in _INSTRUCTIONAL_META_PATTERNS:
        if re.search(pattern, text_lower):
            meta_hits.append(pattern)
    if len(meta_hits) >= 3:
        return {"passed": False, "reason": f"Multiple meta-commentary patterns detected: {meta_hits}"}

    # ── generic template patterns (warn but pass) ──
    generic_hits = []
    for pattern in _GENERIC_TEMPLATE_PATTERNS:
        if re.search(pattern, text_lower):
            generic_hits.append(pattern)
    if len(generic_hits) >= 5:
        return {"passed": False, "reason": f"Excessive generic template patterns: {generic_hits}"}

    return {"passed": True, "reason": None}


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
    skip_critique: bool = True,
) -> str:
    """Generate content via the injected LLM client.

    When sources are provided, they are prepended to the prompt as a
    source-grounding constraint.

    By default (skip_critique=True), returns the draft directly — the
    direct generation path.  When skip_critique=False, runs a two-turn
    self-critique pass that reviews the draft for unverifiable claims.
    """
    extra = ""
    if ct_schema:
        opts = ct_schema.get("optional_params", [])
        if isinstance(opts, list) and opts and isinstance(opts[0], dict):
            extra = "- Options: " + ", ".join(
                p["name"] for p in opts if isinstance(p, dict)
            )

    sources_block = _format_sources_text(sources) if sources else ""

    template = _DIRECT_PROMPT_TEMPLATE if skip_critique else _VERIFIED_PROMPT_TEMPLATE
    llm_prompt = template.format(
        content_type=content_type.replace("_", " "),
        prompt=prompt,
        tone=tone,
        extra_params=extra,
        sources_block=sources_block,
    )

    # Turn 1: generate draft
    draft = await _llm_client.generate(llm_prompt)  # type: ignore[union-attr]

    if skip_critique:
        return draft

    # Turn 2: self-critique pass (verified path only)
    try:
        final = await _self_critique_pass(draft)
        return final
    except Exception:  # noqa: BLE001 — self-critique is best-effort
        return draft


# ---------------------------------------------------------------------------
# embedding helper
# ---------------------------------------------------------------------------

async def _generate_embedding(text: str) -> list[float] | None:
    """Generate a pgvector-compatible embedding via OpenAI API.

    Uses text-embedding-ada-002 (1536 dimensions).  Returns None if
    OPENAI_API_KEY is not set or the API call fails.
    """
    import os

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        import logging
        _log = logging.getLogger("saimon.embedding")
        _log.warning("OPENAI_API_KEY not set — embeddings disabled.")
        return None

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "text-embedding-ada-002",
                    "input": text[:8000],
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["data"][0]["embedding"]
            else:
                import logging
                _log = logging.getLogger("saimon.embedding")
                _log.warning("Embedding API returned %d: %s", resp.status_code, resp.text[:200])
                return None
    except Exception:
        import logging
        _log = logging.getLogger("saimon.embedding")
        _log.warning("Embedding generation failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# knowledge graph persistence
# ---------------------------------------------------------------------------

async def _persist_content_node(
    title: str,
    content_type: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Persist a generated content node to knowledge_graph_nodes.

    Returns the node UUID on success, or None if the DB is unavailable.
    """
    if _db_pool is None:
        return None

    import uuid
    import json

    node_id = str(uuid.uuid4())
    embedding = await _generate_embedding(body)

    meta = metadata or {}
    meta_json = json.dumps(meta)

    try:
        await _db_pool.execute(
            "INSERT INTO knowledge_graph_nodes (id, title, content_type, body, metadata, embedding) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6)",
            node_id, title, content_type, body, meta_json, embedding,
        )
        return node_id
    except Exception:
        import logging
        _log = logging.getLogger("saimon.kg")
        _log.warning("Failed to persist KG node %r", title, exc_info=True)
        return None


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
                skip_critique=True,
            )

            # ── post-generation quality gates ──
            gate = _quality_gate_check(content, content_type)
            if not gate["passed"]:
                logger.log_response(status="error")
                return _error(
                    payload.trace_id,
                    f"Quality gate failed: {gate['reason']}",
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
# tool: generate_verified
# ---------------------------------------------------------------------------

@app.post("/tools/generate_verified")
async def generate_verified(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Generate content with full verification pipeline.

    Currently a stub that runs the verified prompt template with
    self-critique enabled.  Full implementation (SAIMON-EVIDENCE-LOOP #42)
    will chain: generate → evaluate → extract claims → verify each →
    annotate.
    """
    _require_auth(request)

    prompt = payload.parameters.get("prompt")
    if not prompt:
        return _error(payload.trace_id, "Parameter 'prompt' is required.")

    content_type = payload.parameters.get("content_type", "research_note")
    ct_schema = _CONTENT_TYPES.get(content_type)

    logger = build_audit_logger(payload, request, _auth, "generate-mcp")
    logger.log_request(
        content_type=content_type,
        tool="generate_verified",
        prompt_length=len(prompt),
    )

    tone = payload.parameters.get("tone", "neutral")

    if _llm_client is None:
        return _error(payload.trace_id, "LLM backend not available — cannot verify.")

    try:
        content = await _generate_via_llm(
            prompt, content_type, tone, ct_schema,
            sources=payload.sources,
            skip_critique=False,  # enables self-critique pass
        )
        generated: dict[str, Any] = {
            "content": content,
            "content_type": content_type,
            "tone": tone,
            "word_count": len(content.split()),
            "backend": "llm",
            "verified": True,
        }
        resp = _ok(trace_id=payload.trace_id, data=generated)
        logger.log_response(status=resp.status)
        return resp
    except LLMError as exc:
        logger.log_response(status="error")
        return _error(payload.trace_id, f"Verified generation failed: {exc}")


# ---------------------------------------------------------------------------
# tool: self_seed
# ---------------------------------------------------------------------------

@app.post("/tools/self_seed")
async def self_seed(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Generate content from pending seed_requests and persist to KG.

    Idempotent — only processes rows WHERE status = 'pending'.
    Requires both _db_pool and _llm_client to be injected.
    """
    _require_auth(request)

    logger = build_audit_logger(payload, request, _auth, "generate-mcp")
    logger.log_request(content_type=payload.content_type, tool="self_seed")

    if _db_pool is None:
        return _error(payload.trace_id, "Database not available — cannot seed.")
    if _llm_client is None:
        return _error(payload.trace_id, "LLM client not available — cannot seed.")

    try:
        # Read pending seed requests
        rows = await _db_pool.fetch(
            "SELECT id, content_type, prompt, tone, metadata "
            "FROM seed_requests WHERE status = 'pending' "
            "ORDER BY created_at ASC"
        )

        if not rows:
            resp = _ok(
                trace_id=payload.trace_id,
                data={"seeded": 0, "failed": 0, "message": "No pending seed requests."},
            )
            logger.log_response(status=resp.status)
            return resp

        seeded = 0
        failed = 0
        results: list[dict[str, Any]] = []

        for row in rows:
            seed_id = row["id"]
            seed_content_type = row["content_type"]
            seed_prompt = row["prompt"]
            seed_tone = row.get("tone", "neutral")
            seed_meta = row.get("metadata") or {}

            try:
                # Generate content (direct, no critique)
                content = await _generate_via_llm(
                    seed_prompt, seed_content_type, seed_tone,
                    ct_schema=None, sources=None, skip_critique=True,
                )

                # Persist to knowledge graph
                node_id = await _persist_content_node(
                    title=seed_prompt[:200],
                    content_type=seed_content_type,
                    body=content,
                    metadata=seed_meta,
                )

                # Update seed_requests row
                if node_id:
                    await _db_pool.execute(
                        "UPDATE seed_requests SET status = 'complete', result_id = $1 "
                        "WHERE id = $2",
                        node_id, seed_id,
                    )
                else:
                    await _db_pool.execute(
                        "UPDATE seed_requests SET status = 'complete' WHERE id = $1",
                        seed_id,
                    )

                seeded += 1
                results.append({
                    "seed_id": str(seed_id),
                    "node_id": node_id,
                    "content_type": seed_content_type,
                    "status": "seeded",
                })
            except Exception as exc:  # noqa: BLE001 — per-row resilience
                failed += 1
                results.append({
                    "seed_id": str(seed_id),
                    "content_type": seed_content_type,
                    "status": "failed",
                    "error": str(exc)[:200],
                })
                import logging
                _log = logging.getLogger("saimon.self_seed")
                _log.warning("Seed failed for %s: %s", seed_id, exc)

        resp = _ok(
            trace_id=payload.trace_id,
            data={"seeded": seeded, "failed": failed, "results": results},
        )
        logger.log_response(status=resp.status)
        return resp
    except Exception as exc:  # noqa: BLE001
        logger.log_response(status="error")
        return _error(payload.trace_id, f"Self-seed failed: {exc}")


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
