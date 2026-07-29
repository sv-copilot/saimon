"""server.py — evaluate-mcp FastAPI application.

Provides quality-gate evaluation over generated content.  Scores
content against criteria (clarity, completeness, coherence,
conciseness, tone_match) and returns an overall quality score.

Supports LLM injection via set_llm_client() for AI-powered scoring.
Without an LLM, falls back to heuristic-based scoring.
"""

from __future__ import annotations

import json as _json
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.hardening import apply_hardening, build_audit_logger
from research_shared.lifespan import build_lifespan
from research_shared.llm import LLMClient, LLMError

# ---------------------------------------------------------------------------
# backend injection (must be before lifespan)
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None


def set_llm_client(client: LLMClient | None) -> None:
    """Inject an LLMClient for AI-powered evaluation scoring."""
    global _llm_client
    _llm_client = client


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan("evaluate-mcp", llm_client_ref=lambda: _llm_client, llm_client_setter=set_llm_client)
app = FastAPI(title="evaluate-mcp", version="0.1.0", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# auth (fail-closed)
# ---------------------------------------------------------------------------

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)
apply_hardening(app, _auth)


def _require_auth(request: Request) -> None:
    """Fail-closed auth guard.  Called as a FastAPI dependency."""
    if _auth.has_api_key:
        key = _auth.extract_from_headers(dict(request.headers))
        try:
            _auth.validate(key)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


# ---------------------------------------------------------------------------

# criteria registry
# ---------------------------------------------------------------------------

_CRITERIA: dict[str, dict[str, Any]] = {
    "clarity": {
        "name": "clarity",
        "description": "How clear and readable the writing is.",
        "weight": 0.25,
    },
    "completeness": {
        "name": "completeness",
        "description": "How thoroughly the content covers the request.",
        "weight": 0.25,
    },
    "coherence": {
        "name": "coherence",
        "description": "How logically the content flows and connects.",
        "weight": 0.20,
    },
    "conciseness": {
        "name": "conciseness",
        "description": "How appropriately brief and to-the-point the content is.",
        "weight": 0.15,
    },
    "tone_match": {
        "name": "tone_match",
        "description": "How well the tone aligns with the requested tone.",
        "weight": 0.15,
    },
    "ai_detection": {
        "name": "ai_detection",
        "description": "How likely the content was written by a human (1.0) vs AI-generated (0.0).",
        "weight": 1 / 6,
    },
}


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    """Unauthenticated health check."""
    import logging as _logging
    _log = _logging.getLogger("saimon.health")
    llm_ok = False
    if _llm_client is not None:
        try:
            await _llm_client.health_check()
            llm_ok = True
        except Exception:  # noqa: BLE001
            _log.debug("evaluate-mcp health: LLM not reachable", exc_info=True)
    return {
        "status": "ok",
        "service": "evaluate-mcp",
        "checks": {"llm": "connected" if llm_ok else "unavailable"},
    }


# ---------------------------------------------------------------------------
# tool listing
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "evaluate_content",
        "description": "Score content against quality criteria.",
        "parameters": {
            "content": "str (required)",
            "criteria": "list[str] (optional, defaults to all)",
            "tone": "str (optional, for tone_match criterion)",
        },
    },
    {
        "name": "list_criteria",
        "description": "List all evaluation criteria with descriptions and weights.",
        "parameters": {},
    },
    {
        "name": "get_criterion_detail",
        "description": "Get the schema for a specific evaluation criterion.",
        "parameters": {"criterion_name": "str (required)"},
    },
]


@app.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """Return the tool manifest for this MCP."""
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
        trace_id=trace_id,
        status="success",
        data=data,
        citations=citations,
    )


def _degraded(trace_id: str, data: Any = None) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id, status="degraded", data=data,
    )


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="error",
        errors=[message],
    )


# ---------------------------------------------------------------------------
# scoring engine
# ---------------------------------------------------------------------------

_EVAL_PROMPT = """You are a content quality evaluator. Score the following content
against these criteria: {criteria}.

Content: {content}
Tone requested: {tone}

Return ONLY a JSON object with keys:
- "scores": array of {{ "criterion": "...", "score": 0.0-1.0, "justification": "..." }}
- "overall_score": weighted average (0.0-1.0)"""


async def _llm_evaluate(
    criteria_names: list[str], content: str, tone: str | None
) -> list[dict[str, Any]]:
    """Evaluate content via the injected LLM."""
    prompt = _EVAL_PROMPT.format(
        criteria=", ".join(criteria_names),
        content=content[:3000],
        tone=tone or "neutral",
    )
    raw = await _llm_client.generate(prompt)  # type: ignore[union-attr]
    try:
        result = _json.loads(raw)
    except _json.JSONDecodeError:
        return []  # LLM returned malformed JSON — degrade gracefully
    if not isinstance(result, dict):
        return []  # LLM returned non-object JSON — degrade gracefully
    scores = result.get("scores")
    if not scores or not isinstance(scores, list):
        return []  # LLM returned null/missing scores — degrade gracefully
    return scores


import re as _re


def _score_ai_detection(content: str, _tone: str | None = None) -> dict[str, Any]:
    """Score content for AI-generated fingerprints using deterministic heuristics.

    Returns 0.0 (definitely AI) to 1.0 (passes as human).
    """
    if not content or not content.strip():
        return {
            "criterion": "ai_detection",
            "score": 0.5,
            "max_score": 1.0,
            "justification": "Empty content — neutral score.",
        }

    words = content.split()
    word_count = len(words)
    sentences = _re.split(r"[.!?]+", content)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = max(1, len(sentences))

    lines = content.split("\n")
    paragraphs = [l.strip() for l in lines if l.strip()]
    para_count = max(1, len(paragraphs))

    # ---- Check 1: Template phrases ----
    _TEMPLATE_PHRASES = [
        "delve into", "it's worth noting", "moreover", "furthermore",
        "thus", "in conclusion", "as an AI", "it is important to note",
        "crucial to understand", "plays a pivotal role",
    ]
    content_lower = content.lower()
    template_hits = sum(
        1 for phrase in _TEMPLATE_PHRASES if phrase in content_lower
    )
    check1 = max(0.0, 1.0 - (template_hits / sentence_count) * 2)

    # ---- Check 2: Over-hedging ----
    hedge_on_one_hand = content_lower.count("on one hand")
    hedge_on_other = content_lower.count("on the other hand")
    hedge_pairs = min(hedge_on_one_hand, hedge_on_other)
    hedge_however = content_lower.count("however")
    hedge_nevertheless = content_lower.count("nevertheless")
    hedge_total = hedge_pairs + hedge_however + hedge_nevertheless
    hedge_per_100 = hedge_total / max(1, word_count / 100)
    check2 = max(0.0, 1.0 - hedge_per_100)

    # ---- Check 3: Adjective inflation ----
    _ADJECTIVES = [
        "robust", "comprehensive", "crucial", "paramount",
        "multifaceted", "holistic", "dynamic", "vibrant",
    ]
    adj_hits = sum(1 for adj in _ADJECTIVES if adj in content_lower)
    adj_per_100 = adj_hits / max(1, word_count / 100)
    check3 = max(0.0, 1.0 - adj_per_100)

    # ---- Check 4: Bullet-point addiction ----
    bullet_lines = sum(
        1 for line in lines
        if line.strip().startswith(("-", "*"))
        or _re.match(r"^\d+[.)]\s", line.strip())
    )
    non_bullet_lines = sum(
        1 for line in lines
        if line.strip()
        and not line.strip().startswith(("-", "*"))
        and not _re.match(r"^\d+[.)]\s", line.strip())
    )
    total_meaningful = bullet_lines + non_bullet_lines
    if total_meaningful > 0:
        bullet_ratio = bullet_lines / total_meaningful
    else:
        bullet_ratio = 0.0

    if bullet_ratio > 0.7:
        check4 = 0.0
    elif bullet_ratio > 0.4:
        check4 = 0.5
    else:
        check4 = 1.0

    # ---- Check 5: No personal stance ----
    _PERSONAL_MARKERS = [
        "i think", "i found", "in my experience", "i believe",
        "i noticed", "i discovered", "i feel", "i've found",
        "i have found", "in my opinion",
    ]
    personal_hits = sum(
        1 for marker in _PERSONAL_MARKERS if marker in content_lower
    )
    check5 = min(1.0, personal_hits / 2.0)

    # ---- Check 6: Formulaic transitions ----
    _TRANSITIONS = [
        "first", "secondly", "third", "finally", "in conclusion",
        "lastly", "to begin", "next", "additionally",
    ]
    transition_hits = 0
    for para in paragraphs:
        para_lower = para.lower()
        if any(para_lower.startswith(t) for t in _TRANSITIONS):
            transition_hits += 1
    check6 = max(0.0, 1.0 - (transition_hits / para_count))

    # ---- Aggregate ----
    checks = [check1, check2, check3, check4, check5, check6]
    overall = sum(checks) / len(checks)

    # Build justification
    check_labels = []
    if check1 < 0.7:
        check_labels.append(f"{template_hits} template phrases ({check1:.2f})")
    if check2 < 0.7:
        check_labels.append(f"over-hedging ({check2:.2f})")
    if check3 < 0.7:
        check_labels.append(f"{adj_hits} inflated adjectives ({check3:.2f})")
    if check4 < 0.7:
        check_labels.append(f"bullet ratio {bullet_ratio:.0%} ({check4:.2f})")
    if check5 < 0.7:
        check_labels.append(f"no personal stance ({check5:.2f})")
    if check6 < 0.7:
        check_labels.append(f"{transition_hits} formulaic transitions ({check6:.2f})")

    if not check_labels:
        justification = (
            f"AI detection: {overall:.2f}. No strong AI fingerprints detected "
            f"in {word_count} words across {sentence_count} sentences."
        )
    else:
        justification = (
            f"AI detection: {overall:.2f}. Flags: {'; '.join(check_labels)}. "
            f"({word_count} words, {sentence_count} sentences)"
        )

    return {
        "criterion": "ai_detection",
        "score": round(overall, 2),
        "max_score": 1.0,
        "justification": justification,
    }


def _score_criterion(
    criterion: str, content: str, tone: str | None = None
) -> dict[str, Any]:
    """Return a score for a single criterion (heuristic fallback)."""
    word_count = len(content.split())
    char_count = len(content)

    scorers: dict[str, Any] = {
        "clarity": lambda: {
            "score": 0.75,
            "justification": (
                f"Content is {word_count} words. Heuristic clarity score."
            ),
        },
        "completeness": lambda: {
            "score": 0.70,
            "justification": (
                f"Content length: {char_count} chars. Heuristic completeness score."
            ),
        },
        "coherence": lambda: {
            "score": 0.80,
            "justification": "Heuristic coherence score.",
        },
        "conciseness": lambda: {
            "score": 0.85 if word_count < 500 else 0.65,
            "justification": f"Content is {word_count} words. Heuristic conciseness score.",
        },
        "tone_match": lambda: {
            "score": 0.72,
            "justification": f"Requested tone: {tone or 'neutral'}. Heuristic tone_match score.",
        },
        "ai_detection": lambda: _score_ai_detection(content, tone),
    }

    scorer = scorers.get(criterion)
    if scorer is None:
        return {"score": 0.5, "justification": f"Unknown criterion: {criterion}"}

    result = scorer()
    return {
        "criterion": criterion,
        "score": round(result["score"], 2),
        "max_score": 1.0,
        "justification": result["justification"],
    }


def _compute_overall(
    scores: list[dict[str, Any]] | None,
) -> float:
    """Compute a weighted overall score from individual criterion scores."""
    if not scores:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for s in scores:
        criterion_name = s["criterion"]
        weight = _CRITERIA.get(criterion_name, {}).get("weight", 1.0 / len(_CRITERIA))
        weighted_sum += s["score"] * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 2)


# ---------------------------------------------------------------------------
# tool: evaluate_content
# ---------------------------------------------------------------------------

@app.post("/tools/evaluate_content")
async def evaluate_content(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    content = payload.parameters.get("content")
    if not content:
        return _error(payload.trace_id, "Parameter 'content' is required.")

    requested = payload.parameters.get("criteria")
    if requested is not None:
        # Accept comma-separated string, JSON-encoded list, or Python list
        if isinstance(requested, str):
            # Try JSON decode first (handles '["clarity","conciseness"]')
            import json as _json
            try:
                parsed = _json.loads(requested)
                if isinstance(parsed, list):
                    requested = parsed
                else:
                    requested = [c.strip() for c in requested.split(",") if c.strip()]
            except (_json.JSONDecodeError, ValueError):
                requested = [c.strip() for c in requested.split(",") if c.strip()]
        if not isinstance(requested, list):
            return _error(
                payload.trace_id, "Parameter 'criteria' must be a list of strings."
            )
        # Strip quotes/brackets from individual entries
        cleaned: list[str] = []
        for c in requested:
            if not isinstance(c, str):
                return _error(
                    payload.trace_id, "Parameter 'criteria' must be a list of strings."
                )
            cleaned.append(c.strip().strip('"').strip("'").strip("[").strip("]"))
        requested = cleaned
        # Validate all requested criteria exist
        unknown = [c for c in requested if c not in _CRITERIA]
        if unknown:
            supported = ", ".join(sorted(_CRITERIA.keys()))
            return _error(
                payload.trace_id,
                f"Unknown criteria: {', '.join(repr(u) for u in unknown)}. "
                f"Supported: {supported}.",
            )
        criteria_names = requested
    else:
        criteria_names = list(_CRITERIA.keys())

    tone = payload.parameters.get("tone")

    logger = build_audit_logger(payload, request, _auth, "evaluate-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="evaluate_content",
        content_length=len(content),
        criteria_count=len(criteria_names),
    )

    # Score each criterion — try LLM first, fall back to heuristic
    if _llm_client is not None:
        try:
            scores = await _llm_evaluate(criteria_names, content, tone)
        except (LLMError, NotImplementedError, _json.JSONDecodeError):
            scores = [_score_criterion(c, content, tone) for c in criteria_names]
    else:
        scores = [_score_criterion(c, content, tone) for c in criteria_names]

    # Compute overall score
    overall = _compute_overall(scores)

    citations = (
        [s.identifier for s in payload.sources] if payload.sources else []
    )

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "scores": scores,
            "overall_score": overall,
            "criteria_count": len(scores),
        },
        citations=citations,
    )
    logger.log_response(
        status=resp.status, citations_count=len(resp.citations or [])
    )
    return resp


# ---------------------------------------------------------------------------
# tool: list_criteria
# ---------------------------------------------------------------------------

@app.post("/tools/list_criteria")
async def list_criteria(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    logger = build_audit_logger(payload, request, _auth, "evaluate-mcp")
    logger.log_request(content_type=payload.content_type, tool="list_criteria")

    criteria = [
        {
            "name": name,
            "description": schema["description"],
            "weight": schema["weight"],
        }
        for name, schema in _CRITERIA.items()
    ]

    resp = _ok(trace_id=payload.trace_id, data={"criteria": criteria})
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: get_criterion_detail
# ---------------------------------------------------------------------------

@app.post("/tools/get_criterion_detail")
async def get_criterion_detail(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    criterion_name = payload.parameters.get("criterion_name")
    if not criterion_name:
        return _error(
            payload.trace_id, "Parameter 'criterion_name' is required."
        )

    logger = build_audit_logger(payload, request, _auth, "evaluate-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="get_criterion_detail",
        criterion_name=criterion_name,
    )

    schema = _CRITERIA.get(criterion_name)
    if schema is None:
        supported = ", ".join(sorted(_CRITERIA.keys()))
        return _error(
            payload.trace_id,
            f"Unknown criterion: {criterion_name!r}. "
            f"Supported: {supported}.",
        )

    resp = _ok(trace_id=payload.trace_id, data=schema)
    logger.log_response(status=resp.status)
    return resp
