"""server.py — evaluate-mcp FastAPI application.

Provides quality-gate evaluation over generated content.  Scores
content against criteria (clarity, completeness, coherence,
conciseness, tone_match) and returns an overall quality score.
Every tool endpoint accepts a ResearchRequest envelope and returns
a ResearchResponse envelope.  Authentication is fail-closed.
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

app = FastAPI(title="evaluate-mcp", version="0.1.0")

# ---------------------------------------------------------------------------
# auth (fail-closed)
# ---------------------------------------------------------------------------

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)


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
}


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    """Unauthenticated health check."""
    return {"status": "ok", "service": "evaluate-mcp"}


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


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="error",
        errors=[message],
    )


# ---------------------------------------------------------------------------
# scoring engine
# ---------------------------------------------------------------------------

def _score_criterion(
    criterion: str, content: str, tone: str | None = None
) -> dict[str, Any]:
    """Return a score for a single criterion.

    Placeholder — in production this uses the LLM via
    research_shared.llm to evaluate content quality.
    """
    # Base scores derived from simple heuristics on content length
    word_count = len(content.split())
    char_count = len(content)

    scorers: dict[str, Any] = {
        "clarity": lambda: {
            "score": 0.75,
            "justification": (
                f"Content is {word_count} words. Placeholder clarity "
                "score — production evaluation would use LLM analysis."
            ),
        },
        "completeness": lambda: {
            "score": 0.70,
            "justification": (
                f"Content length: {char_count} chars. Placeholder completeness "
                "score — production evaluation would use LLM analysis."
            ),
        },
        "coherence": lambda: {
            "score": 0.80,
            "justification": (
                "Placeholder coherence score — production evaluation "
                "would use LLM to assess logical flow."
            ),
        },
        "conciseness": lambda: {
            "score": 0.85 if word_count < 500 else 0.65,
            "justification": (
                f"Content is {word_count} words. "
                "Placeholder conciseness score — production evaluation "
                "would use LLM analysis."
            ),
        },
        "tone_match": lambda: {
            "score": 0.72,
            "justification": (
                f"Requested tone: {tone or 'neutral'}. "
                "Placeholder tone_match score — production evaluation "
                "would use LLM analysis."
            ),
        },
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
    scores: list[dict[str, Any]],
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
        if not isinstance(requested, list):
            return _error(
                payload.trace_id, "Parameter 'criteria' must be a list of strings."
            )
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

    logger = AuditLogger(trace_id=payload.trace_id, service_name="evaluate-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="evaluate_content",
        content_length=len(content),
        criteria_count=len(criteria_names),
    )

    # Score each criterion
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

    logger = AuditLogger(trace_id=payload.trace_id, service_name="evaluate-mcp")
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

    logger = AuditLogger(trace_id=payload.trace_id, service_name="evaluate-mcp")
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
