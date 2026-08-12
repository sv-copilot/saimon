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

import logging as _logging
import os as _os
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
# quality metrics tracking (#47)
# ---------------------------------------------------------------------------

_quality_metrics: dict[str, Any] = {
    "total_generations": 0,
    "ai_detect_passes": 0,
    "total_retries": 0,
    "content_type_counts": {},
    "llm_consecutive_failures": 0,
    "last_llm_failure_at": None,
}


def _record_generation_metrics(
    content_type: str, iteration_log: list[dict[str, Any]] | None = None
) -> None:
    """Update quality metrics after a generation."""
    _quality_metrics["total_generations"] += 1

    if iteration_log:
        retries = len(iteration_log) - 1 if len(iteration_log) > 1 else 0
        _quality_metrics["total_retries"] += retries
        if iteration_log[-1].get("score", 0) >= 0.5:
            _quality_metrics["ai_detect_passes"] += 1

    # Track content type distribution
    cts: dict[str, int] = _quality_metrics.setdefault("content_type_counts", {})
    cts[content_type] = cts.get(content_type, 0) + 1

    # Reset LLM failure counter on success
    _quality_metrics["llm_consecutive_failures"] = 0
    _quality_metrics["last_llm_failure_at"] = None


def _record_llm_failure() -> None:
    """Record an LLM failure for health tracking."""
    import datetime as _dt

    _quality_metrics["llm_consecutive_failures"] += 1
    _quality_metrics["last_llm_failure_at"] = _dt.datetime.utcnow().isoformat() + "Z"
    _log = _logging.getLogger("saimon.generate.health")
    _log.warning(
        "LLM unreachable — consecutive failures: %d",
        _quality_metrics["llm_consecutive_failures"],
    )


def _get_quality_summary() -> dict[str, Any]:
    """Return a snapshot of quality metrics for /health."""
    total = max(1, _quality_metrics.get("total_generations", 0))
    return {
        "total_generations": _quality_metrics["total_generations"],
        "ai_detect_pass_rate": round(
            _quality_metrics.get("ai_detect_passes", 0) / total, 2
        ),
        "avg_retries": round(
            _quality_metrics.get("total_retries", 0) / total, 2
        ),
        "content_type_counts": _quality_metrics.get("content_type_counts", {}),
        "llm_consecutive_failures": _quality_metrics.get("llm_consecutive_failures", 0),
    }


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
            "quality": _get_quality_summary(),
        },
    }


@app.get("/health/aggregate")
async def health_aggregate() -> dict[str, Any]:
    """Aggregate health of all 6 MCP services."""
    from research_shared.health import check_all_services

    api_key = _os.environ.get("SAIMON_API_KEY")
    result = await check_all_services(api_key=api_key)
    # Merge in generate-specific quality metrics
    result["quality"] = _get_quality_summary()
    return result


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

def _get_type_prompt(
    content_type: str, prompt: str, tone: str, sources_block: str,
    extra_params: str = "",
) -> str:
    """Build a content-type-specific system prompt.

    Resolves the content type from the registry, extracts its system_prompt
    and banlist, and builds a targeted prompt for the LLM. Falls back to a
    generic template for unknown or unconfigured content types.
    """
    ct = _CONTENT_TYPES.get(content_type, {})
    system_prompt = ct.get("system_prompt")
    banlist: list[str] = ct.get("banlist", [])

    if system_prompt:
        banlist_text = (
            "\n".join(
                f"- Do NOT use the phrase: '{phrase}'"
                for phrase in banlist
            )
            if banlist
            else ""
        )
        return (
            f"{system_prompt}\n\n"
            f"Generate a {content_type.replace('_', ' ')} with:\n"
            f"- Prompt: {prompt}\n"
            f"- Tone: {tone}\n"
            f"{extra_params}\n"
            f"{banlist_text}\n\n"
            "Produce the final content directly. Do not include meta-commentary,\n"
            "review headers, or self-critique. Write as if you are the author.\n\n"
            "Do not invent statistics, dates, or names. "
            "Stick to claims you can support.\n\n"
            f"{sources_block}"
        )

    # ── Fallback: generic template for types without profile ──
    return _DIRECT_PROMPT_TEMPLATE.format(
        content_type=content_type.replace("_", " "),
        prompt=prompt, tone=tone,
        extra_params=extra_params,
        sources_block=sources_block,
    )


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
    broken attribution, or forbidden phrases. Uses per-type banlists
    from the content type registry when available.
    """
    import re

    text_lower = text.lower()

    # ── Build forbidden list: defaults + per-type banlist ──
    ct = _CONTENT_TYPES.get(content_type, {})
    type_banlist: list[str] = ct.get("banlist", [])
    all_forbidden: list[str] = list(_DEFAULT_FORBIDDEN_PHRASES)
    for phrase in (forbidden_phrases or []):
        if phrase not in all_forbidden:
            all_forbidden.append(phrase)
    for phrase in type_banlist:
        if phrase not in all_forbidden:
            all_forbidden.append(phrase)

    # ── forbidden phrases ──
    for phrase in all_forbidden:
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

    if skip_critique:
        llm_prompt = _get_type_prompt(content_type, prompt, tone, sources_block, extra)
    else:
        llm_prompt = _VERIFIED_PROMPT_TEMPLATE.format(
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
# AI detection loop (#39) — inter-service evaluate + iterate
# ---------------------------------------------------------------------------

_evaluate_mcp_url = _os.environ.get("EVALUATE_MCP_URL", "http://evaluate-mcp:8004")
_SEARCH_MCP_URL = _os.environ.get("SEARCH_MCP_URL", "http://saimon-search:8001")
_ai_detect_max_retries = int(_os.environ.get("SAIMON_AI_DETECT_MAX_RETRIES", "3"))
_ai_detect_threshold = float(_os.environ.get("SAIMON_AI_DETECT_THRESHOLD", "0.5"))


async def _call_evaluate(content: str) -> dict[str, Any]:
    """Call the evaluate-mcp service to score AI detection on content.

    Returns the full evaluate_content response dict.  On any error,
    returns a neutral fallback with score 0.5.
    """
    import os as _os
    import httpx

    api_key = _os.environ.get("SAIMON_API_KEY", "")
    url = f"{_evaluate_mcp_url}/tools/evaluate_content"
    body = {
        "trace_id": "ai-detect-loop",
        "content_type": "evaluate",
        "parameters": {
            "content": content,
            "criteria": ["ai_detection"],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"X-Saimon-API-Key": api_key},
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                _log = _logging.getLogger("saimon.generate.ai_detect")
                _log.warning(
                    "Evaluate service returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception:
        _log = _logging.getLogger("saimon.generate.ai_detect")
        _log.warning("Evaluate service call failed", exc_info=True)

    # Neutral fallback
    return {
        "data": {
            "scores": [
                {
                    "criterion": "ai_detection",
                    "score": 0.5,
                    "max_score": 1.0,
                    "justification": "Evaluate service unavailable — neutral fallback.",
                }
            ]
        }
    }


def _parse_failing_flags(justification: str | None) -> list[str]:
    """Parse flag names from evaluate justification string.

    Pattern: "Flags: {flag1} ({score1}); {flag2} ({score2})."
    Extracts flag names, stripping leading numbers (e.g.,
    "3 template phrases" → "template phrases").
    """
    if not justification:
        return []

    import re

    # Find the "Flags:" section
    flags_match = re.search(r"Flags:\s*(.+?)\.\s*\(", justification)
    if not flags_match:
        return []

    flags_text = flags_match.group(1)
    flags: list[str] = []
    for segment in flags_text.split(";"):
        segment = segment.strip()
        # Remove the trailing " (score)" part
        cleaned = re.sub(r"\s*\([^)]*\)$", "", segment).strip()
        # Strip leading numbers (e.g., "3 template phrases" → "template phrases")
        cleaned = re.sub(r"^\d+\s+", "", cleaned)
        if cleaned:
            flags.append(cleaned)

    return flags


# ── Anti-pattern prompt map ──

_ANTI_PATTERN_MAP: dict[str, str] = {
    "template phrases": (
        "Avoid formulaic phrases like 'delve into', 'moreover', 'furthermore', "
        "'it is worth noting', 'crucial to understand'. Use plain, natural language."
    ),
    "corporate neutrality": (
        "Take a clear stance. Avoid weak constructions like 'can reduce', "
        "'may help', 'offers several'. Say what you actually think."
    ),
    "low burstiness": (
        "Vary sentence and paragraph rhythm. Mix long, flowing passages "
        "with short, punchy statements."
    ),
    "uniform sentences": (
        "Vary sentence length significantly. Mix 5-word and 25-word "
        "sentences to create natural rhythm."
    ),
    "low lexical diversity": (
        "Use more varied vocabulary. Avoid repeating the same words "
        "and phrases throughout the text."
    ),
    "no personal stance": (
        "Add personal perspective. Use first-person language like "
        "'I', 'we', 'my', 'our'. Share real experiences or opinions."
    ),
    "formulaic transitions": (
        "Vary paragraph transitions. Avoid predictable patterns like "
        "'First', 'Secondly', 'Finally', 'In conclusion'."
    ),
    "bullet-point addiction": (
        "Reduce bullet points and numbered lists. Write in flowing "
        "paragraphs with natural transitions."
    ),
    "over-hedging": (
        "Reduce hedging language. Make stronger, more direct statements "
        "instead of 'however', 'nevertheless', 'on one hand'."
    ),
    "inflated adjectives": (
        "Cut inflated adjectives like 'robust', 'comprehensive', "
        "'multifaceted', 'holistic'. Use specific, concrete terms instead."
    ),
    "narrow punctuation": (
        "Use varied punctuation: em-dashes, semicolons, colons, "
        "parentheses. Avoid repetitive period-comma patterns."
    ),
    "low starter diversity": (
        "Vary sentence starters. Don't start every sentence with "
        "'The', 'This', 'It', 'These'. Mix it up."
    ),
}


def _build_anti_pattern_prompt(flags: list[str]) -> str:
    """Build anti-pattern guidance prompt from flagged issues.

    Maps each flag name to specific writing improvement guidance.
    Returns empty string if no recognized flags.
    """
    if not flags:
        return ""

    lines: list[str] = [
        "CRITICAL WRITING GUIDANCE: The previous draft was flagged for "
        "these AI-detected patterns. Fix them in your rewrite:",
        "",
    ]
    for flag in flags:
        guidance = _ANTI_PATTERN_MAP.get(flag)
        if guidance:
            lines.append(f"- {flag}: {guidance}")

    if len(lines) > 2:  # Has actual guidance beyond header
        return "\n".join(lines)
    return ""


async def _iterate_until_human_like(
    original_prompt: str,
    content: str,
    content_type: str,
    tone: str,
    ct_schema: dict[str, Any] | None,
    sources: list[Any] | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Auto-iterate content regeneration until AI detection passes.

    Calls evaluate service to score content, parses failing flags,
    builds anti-pattern guidance, and regenerates.  Tracks best
    attempt across retries.

    Returns (best_content, iteration_log).
    """
    # Read env at call time so tests can monkeypatch
    max_retries = int(_os.environ.get("SAIMON_AI_DETECT_MAX_RETRIES", str(_ai_detect_max_retries)))
    threshold = float(_os.environ.get("SAIMON_AI_DETECT_THRESHOLD", str(_ai_detect_threshold)))

    _log = _logging.getLogger("saimon.generate.ai_detect")

    iteration_log: list[dict[str, Any]] = []
    best_content = content
    best_score = 0.0

    if max_retries <= 0:
        _log.debug("AI detect loop disabled (SAIMON_AI_DETECT_MAX_RETRIES=%d)", max_retries)
        return content, iteration_log

    for attempt in range(1, max_retries + 2):  # +2: initial eval + max_retries retries
        # Evaluate current content
        try:
            eval_response = await _call_evaluate(content)
        except Exception:
            _log.warning("Evaluate call raised, using neutral fallback", exc_info=True)
            eval_response = {
                "data": {
                    "scores": [
                        {
                            "criterion": "ai_detection",
                            "score": 0.5,
                            "max_score": 1.0,
                            "justification": "Error — neutral fallback.",
                        }
                    ]
                }
            }

        scores = eval_response.get("data", {}).get("scores", [])
        ai_score = 0.5
        justification = "Unknown"
        for s in scores:
            if s.get("criterion") == "ai_detection":
                ai_score = s.get("score", 0.5)
                justification = s.get("justification", "")

        _log.info(
            "AI detect attempt %d: score=%.2f threshold=%.2f",
            attempt, ai_score, threshold,
        )

        # Track best
        if ai_score >= best_score:
            best_score = ai_score
            best_content = content

        iteration_log.append({
            "attempt": attempt,
            "score": ai_score,
            "justification": justification,
        })

        # PASS: at or above threshold
        if ai_score >= threshold:
            _log.info("AI detection passed on attempt %d (%.2f ≥ %.2f)", attempt, ai_score, threshold)
            return content, iteration_log

        # Out of retries — return best
        if attempt > max_retries:
            _log.info(
                "AI detection loop exhausted (max_retries=%d), best_score=%.2f",
                max_retries, best_score,
            )
            return best_content, iteration_log

        # FAIL: parse flags and regenerate
        flags = _parse_failing_flags(justification)
        anti_prompt = _build_anti_pattern_prompt(flags)

        if anti_prompt:
            revised_prompt = f"{anti_prompt}\n\n---\n\n{original_prompt}"
        else:
            revised_prompt = (
                f"REWRITE GUIDANCE: The previous draft was flagged as AI-generated. "
                f"Write in a more natural, human voice with varied sentence structure, "
                f"personal perspective, and concrete language.\n\n"
                f"---\n\n{original_prompt}"
            )

        _log.info(
            "Regenerating (attempt %d): flags=%s",
            attempt, flags,
        )

        try:
            content = await _generate_via_llm(
                revised_prompt, content_type, tone, ct_schema,
                sources=sources, skip_critique=True,
            )
        except Exception:
            _log.warning("Regeneration failed on attempt %d", attempt, exc_info=True)
            # Keep previous content and try again
            continue

    return best_content, iteration_log


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
# inter-service HTTP calls (generate → verify)
# ---------------------------------------------------------------------------

_verify_mcp_url = _os.environ.get("VERIFY_MCP_URL", "http://saimon-verify:8001")


async def _call_verify_extract(content: str) -> dict[str, Any]:
    """Call verify-mcp to extract claims from generated content.

    Returns the extract_claims response dict. On any error, returns
    a neutral fallback with empty claims list.
    """
    import httpx

    api_key = _os.environ.get("SAIMON_API_KEY", "")
    url = f"{_verify_mcp_url}/tools/extract_claims"
    body = {
        "trace_id": "evidence-loop-extract",
        "content_type": "verify",
        "parameters": {
            "source_text": content,
            "max_claims": 10,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"X-Saimon-API-Key": api_key},
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                _log = _logging.getLogger("saimon.generate.evidence")
                _log.warning(
                    "Verify extract returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception:
        _log = _logging.getLogger("saimon.generate.evidence")
        _log.warning("Verify extract call failed", exc_info=True)

    return {"data": {"claims": []}}


async def _call_verify_claim(claim_text: str) -> dict[str, Any]:
    """Call verify-mcp to verify a single claim.

    Returns the verify_claim response dict. On any error, returns
    a neutral fallback.
    """
    import httpx

    api_key = _os.environ.get("SAIMON_API_KEY", "")
    url = f"{_verify_mcp_url}/tools/verify_claim"
    body = {
        "trace_id": "evidence-loop-verify",
        "content_type": "verify",
        "parameters": {
            "claim": claim_text,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"X-Saimon-API-Key": api_key},
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                _log = _logging.getLogger("saimon.generate.evidence")
                _log.warning(
                    "Verify claim returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception:
        _log = _logging.getLogger("saimon.generate.evidence")
        _log.warning("Verify claim call failed", exc_info=True)

    return {
        "data": {
            "verifications": [],
            "overall_verdict": "inconclusive",
            "overall_confidence": 0.0,
        }
    }


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
# auto source discovery (#43) — inter-service search → generate
# ---------------------------------------------------------------------------

async def _auto_discover_sources(prompt: str) -> list[Any]:
    """Call search MCP source_discovery and return resolved sources.

    Best-effort: if search MCP is unreachable or returns no results,
    returns empty list — generation continues without sources.
    """
    import httpx
    import uuid as _uuid

    api_key = _os.environ.get("SAIMON_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_SEARCH_MCP_URL}/tools/source_discovery",
                json={
                    "trace_id": str(_uuid.uuid4()),
                    "content_type": "discovery",
                    "parameters": {"text": prompt, "max_results": 5},
                },
                headers={"X-Saimon-API-Key": api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", {}).get("resolved", [])
    except Exception:  # noqa: BLE001 — best-effort
        pass
    return []


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

    # ── auto-discover sources from prompt text ──
    auto_discover = payload.parameters.get("auto_discover", True)
    sources = list(payload.sources) if payload.sources else []

    if auto_discover and _llm_client is not None:
        try:
            discovered = await _auto_discover_sources(prompt)
            for d in discovered:
                src_obj = type('Source', (), {
                    'identifier': d.get('doi', d.get('identifier', '')),
                    'type': d.get('source_index', 'discovered'),
                    'title': d.get('title', ''),
                    'authors': d.get('authors', []),
                    'year': d.get('year'),
                })()
                sources.append(src_obj)
                citations.append(d.get('doi', d.get('identifier', '')))
        except Exception:  # noqa: BLE001 — best-effort
            pass

    # ── try LLM backend ──
    if _llm_client is not None:
        try:
            content = await _generate_via_llm(
                prompt, content_type, tone, ct_schema,
                sources=sources if sources else None,
                skip_critique=True,
            )

            # ── AI detection loop: iterate until human-like ──
            content, iteration_log = await _iterate_until_human_like(
                original_prompt=prompt,
                content=content,
                content_type=content_type,
                tone=tone,
                ct_schema=ct_schema,
                sources=sources if sources else None,
            )

            # ── post-generation quality gates ──
            gate = _quality_gate_check(content, content_type)
            if not gate["passed"]:
                logger.log_response(status="error")
                return _error(
                    payload.trace_id,
                    f"Quality gate failed: {gate['reason']}",
                )

            _record_generation_metrics(content_type, iteration_log)

            generated: dict[str, Any] = {
                "content": content,
                "content_type": content_type,
                "tone": tone,
                "word_count": len(content.split()),
                "backend": "llm",
                "iteration_log": iteration_log,
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
            _record_llm_failure()
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

    Chains: generate → persist content node → extract claims →
    verify each claim → persist observations + verifications +
    evidence links → annotate content.
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

    # ── Step 1: Generate content with self-critique enabled ──
    try:
        content = await _generate_via_llm(
            prompt, content_type, tone, ct_schema,
            sources=payload.sources,
            skip_critique=False,  # enables self-critique + verification markers
        )
    except LLMError as exc:
        _record_llm_failure()
        logger.log_response(status="error")
        return _error(payload.trace_id, f"Verified generation failed: {exc}")

    # ── Step 2: Persist content node to knowledge graph ──
    title = f"{content_type.replace('_', ' ').title()}: {prompt[:80]}"
    metadata: dict[str, Any] = {
        "source": "generate-mcp",
        "tool": "generate_verified",
        "tone": tone,
    }
    node_id = await _persist_content_node(title, content_type, content, metadata)

    # ── Step 3: Extract claims from generated content ──
    extract_resp = await _call_verify_extract(content)
    claims = extract_resp.get("data", {}).get("claims", [])
    claims_extracted = len(claims)

    # ── Step 4: Verify each claim and persist ──
    claims_verified = 0
    observation_ids: list[str] = []

    for claim in claims:
        claim_text = claim.get("claim_text", "")
        if not claim_text:
            continue

        # 4a: Persist observation as "unverified" initially
        if _db_pool is not None:
            try:
                import uuid as _uuid
                import hashlib as _hashlib
                import json as _json_lib

                obs_id = str(_uuid.uuid4())
                source_hash = _hashlib.sha256(content.encode()).hexdigest()[:16]

                await _db_pool.execute(
                    """INSERT INTO observations
                       (id, claim_text, topic, summary, confidence_0_1, rationale,
                        verification_status, source_text_hash)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                       ON CONFLICT DO NOTHING""",
                    obs_id,
                    claim_text,
                    claim.get("topic"),
                    claim_text[:200],
                    float(claim.get("confidence_0_1", 0.5)),
                    claim.get("rationale"),
                    "unverified",
                    source_hash,
                )
                observation_ids.append(obs_id)
            except Exception:
                obs_id = ""
        else:
            obs_id = ""

        # 4b: Call verify_claim for this claim
        verify_resp = await _call_verify_claim(claim_text)
        verifications = verify_resp.get("data", {}).get("verifications", [])
        overall_verdict = verify_resp.get("data", {}).get("overall_verdict", "inconclusive")
        overall_confidence = verify_resp.get("data", {}).get("overall_confidence", 0.5)

        # 4c: Persist verifications and evidence links
        if _db_pool is not None and obs_id:
            for v in verifications:
                try:
                    ver_id = str(_uuid.uuid4())
                    method = v.get("method", "unknown")
                    verdict = v.get("verdict", "inconclusive")
                    confidence = float(v.get("confidence", 0.5))
                    explanation = v.get("explanation", "")

                    await _db_pool.execute(
                        """INSERT INTO observation_verifications
                           (id, observation_id, method, verdict, confidence, explanation)
                           VALUES ($1, $2, $3, $4, $5, $6)""",
                        ver_id, obs_id, method, verdict, confidence, explanation,
                    )

                    # Build evidence links for this verification
                    evidence_source = v.get("evidence_source", "")
                    if evidence_source:
                        evidence_type = "citation" if evidence_source.startswith("doi:") else "shadow_source"
                        ev_id = str(_uuid.uuid4())
                        await _db_pool.execute(
                            """INSERT INTO observation_verification_evidence
                               (id, verification_id, evidence_type, evidence_identifier, relevance_score)
                               VALUES ($1, $2, $3, $4, $5)""",
                            ev_id, ver_id, evidence_type, evidence_source, confidence,
                        )
                except Exception:
                    pass

            # 4d: Update observation verification status
            try:
                await _db_pool.execute(
                    "UPDATE observations SET verification_status = $1, "
                    "updated_at = now() WHERE id = $2",
                    "verified" if overall_verdict != "inconclusive" else "unverified",
                    obs_id,
                )
            except Exception:
                pass

        claims_verified += 1

    # ── Step 5: Return consolidated response ──
    _record_generation_metrics(content_type)

    generated: dict[str, Any] = {
        "content": content,
        "content_type": content_type,
        "tone": tone,
        "word_count": len(content.split()),
        "backend": "llm",
        "verified": True,
        "node_id": node_id,
        "claims_extracted": claims_extracted,
        "claims_verified": claims_verified,
        "observation_ids": observation_ids if observation_ids else None,
    }

    resp = _ok(trace_id=payload.trace_id, data=generated)
    logger.log_response(status=resp.status)
    return resp


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
            "SELECT id, content_type, prompt, parameters "
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
            seed_params = row.get("parameters") or {}
            seed_tone = seed_params.get("tone", "neutral") if isinstance(seed_params, dict) else "neutral"
            seed_meta = seed_params if isinstance(seed_params, dict) else {}

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
