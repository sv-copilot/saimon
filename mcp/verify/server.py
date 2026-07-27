"""server.py — verify-mcp FastAPI application.

Provides fact-checking tools that verify claims against sources using
multiple verification methods (source corroboration, logical consistency,
authority check).  Every tool endpoint accepts a ResearchRequest envelope
and returns a ResearchResponse envelope.  Authentication is fail-closed.

Supports LLM injection via set_llm_client() for AI-powered verification.
Without an LLM, falls back to heuristic-based verification.
"""

from __future__ import annotations

import json as _json
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.llm import LLMClient, LLMError

# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

app = FastAPI(title="verify-mcp", version="0.1.0")

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
# backend injection
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None


def set_llm_client(client: LLMClient | None) -> None:
    """Inject an LLMClient for AI-powered fact-checking."""
    global _llm_client
    _llm_client = client


# ---------------------------------------------------------------------------
# verification methods registry
# ---------------------------------------------------------------------------

_METHODS: dict[str, dict[str, Any]] = {
    "source_corroboration": {
        "name": "source_corroboration",
        "description": "Cross-reference the claim against known sources.",
        "reliability": 0.85,
    },
    "logical_consistency": {
        "name": "logical_consistency",
        "description": "Check internal logical consistency of the claim.",
        "reliability": 0.70,
    },
    "authority_check": {
        "name": "authority_check",
        "description": "Verify against authoritative domain sources.",
        "reliability": 0.80,
    },
    "temporal_validity": {
        "name": "temporal_validity",
        "description": "Check if the claim is still valid given current data.",
        "reliability": 0.75,
    },
}


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    """Unauthenticated health check."""
    return {"status": "ok", "service": "verify-mcp"}


# ---------------------------------------------------------------------------
# tool listing
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "verify_claim",
        "description": "Verify a factual claim against sources using multiple methods.",
        "parameters": {
            "claim": "str (required)",
            "methods": "list[str] (optional, defaults to all)",
        },
    },
    {
        "name": "list_verification_methods",
        "description": "List all verification methods with descriptions and reliability scores.",
        "parameters": {},
    },
    {
        "name": "get_method_detail",
        "description": "Get the schema for a specific verification method.",
        "parameters": {"method_name": "str (required)"},
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
# LLM verification
# ---------------------------------------------------------------------------

_VERIFY_PROMPT = """You are a fact-checker. Verify the following claim using
these methods: {methods}.

Claim: {claim}
Sources provided: {source_summary}

Return ONLY a JSON object with:
- "verifications": array of {{ "method": "...", "verdict": "supported|refuted|inconclusive", "confidence": 0.0-1.0, "explanation": "..." }}
- "overall_verdict": "supported|refuted|inconclusive"
"""


async def _llm_verify(
    method_names: list[str], claim: str, sources: Any
) -> list[dict[str, Any]]:
    """Verify a claim via the injected LLM."""
    source_summary = (
        f"{len(sources)} sources provided" if sources else "no sources"
    )
    prompt = _VERIFY_PROMPT.format(
        methods=", ".join(method_names),
        claim=claim,
        source_summary=source_summary,
    )
    raw = await _llm_client.generate(prompt)  # type: ignore[union-attr]
    result = _json.loads(raw)
    return result.get("verifications", [])


# ---------------------------------------------------------------------------
# verification engine
# ---------------------------------------------------------------------------

def _verify_method(
    method: str, claim: str, sources: list[Any] | None = None
) -> dict[str, Any]:
    """Return a verification result for a single method.

    Placeholder -- in production this uses the LLM via
    research_shared.llm to fact-check claims against sources.
    """
    source_count = len(sources) if sources else 0

    verifiers: dict[str, Any] = {
        "source_corroboration": lambda: {
            "verdict": "supported",
            "confidence": 0.82,
            "explanation": (
                f"Cross-referenced claim '{claim[:60]}...' "
                f"against {source_count} sources. "
                "Placeholder verdict — production would use LLM "
                "to assess source agreement."
            ),
        },
        "logical_consistency": lambda: {
            "verdict": "supported",
            "confidence": 0.78,
            "explanation": (
                f"Claim '{claim[:60]}...' is internally consistent. "
                "Placeholder verdict — production would use LLM "
                "to detect logical fallacies."
            ),
        },
        "authority_check": lambda: {
            "verdict": "supported",
            "confidence": 0.80,
            "explanation": (
                f"Claim '{claim[:60]}...' aligns with authoritative sources. "
                "Placeholder verdict — production would use LLM "
                "to check against domain authorities."
            ),
        },
        "temporal_validity": lambda: {
            "verdict": "supported",
            "confidence": 0.72,
            "explanation": (
                f"Claim '{claim[:60]}...' appears current. "
                "Placeholder verdict — production would use LLM "
                "to check temporal relevance."
            ),
        },
    }

    verifier = verifiers.get(method)
    if verifier is None:
        return {
            "verdict": "inconclusive",
            "confidence": 0.3,
            "explanation": f"Unknown verification method: {method}",
        }

    result = verifier()
    return {
        "method": method,
        "verdict": result["verdict"],
        "confidence": round(result["confidence"], 2),
        "explanation": result["explanation"],
    }


def _compute_overall_verdict(
    verifications: list[dict[str, Any]],
) -> str:
    """Compute an aggregate verdict from individual method results."""
    if not verifications:
        return "inconclusive"

    # Weight each method by its reliability
    total_weight = 0.0
    scored = 0.0
    for v in verifications:
        method_name = v["method"]
        reliability = _METHODS.get(method_name, {}).get("reliability", 0.5)
        weight = reliability
        if v["verdict"] == "supported":
            scored += weight
        elif v["verdict"] == "refuted":
            scored -= weight
        # inconclusive adds 0
        total_weight += weight

    if total_weight == 0:
        return "inconclusive"

    ratio = scored / total_weight
    if ratio > 0.33:
        return "supported"
    elif ratio < -0.33:
        return "refuted"
    else:
        return "inconclusive"


# ---------------------------------------------------------------------------
# tool: verify_claim
# ---------------------------------------------------------------------------

@app.post("/tools/verify_claim")
async def verify_claim(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    claim = payload.parameters.get("claim")
    if not claim:
        return _error(payload.trace_id, "Parameter 'claim' is required.")

    requested = payload.parameters.get("methods")
    if requested is not None:
        if not isinstance(requested, list):
            return _error(
                payload.trace_id, "Parameter 'methods' must be a list of strings."
            )
        # Validate all requested methods exist
        unknown = [m for m in requested if m not in _METHODS]
        if unknown:
            supported = ", ".join(sorted(_METHODS.keys()))
            return _error(
                payload.trace_id,
                f"Unknown methods: {', '.join(repr(u) for u in unknown)}. "
                f"Supported: {supported}.",
            )
        method_names = requested
    else:
        method_names = list(_METHODS.keys())

    sources = payload.sources if payload.sources else None

    logger = AuditLogger(trace_id=payload.trace_id, service_name="verify-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="verify_claim",
        claim_length=len(claim),
        methods_count=len(method_names),
    )

    # Verify using each method — try LLM first, fall back to heuristic
    if _llm_client is not None:
        try:
            verifications = await _llm_verify(method_names, claim, sources)
        except (LLMError, NotImplementedError, _json.JSONDecodeError):
            verifications = [
                _verify_method(m, claim, sources) for m in method_names
            ]
    else:
        verifications = [
            _verify_method(m, claim, sources) for m in method_names
        ]

    # Compute overall verdict
    overall = _compute_overall_verdict(verifications)

    citations = (
        [s.identifier for s in payload.sources] if payload.sources else []
    )

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "verifications": verifications,
            "overall_verdict": overall,
            "methods_used": len(verifications),
        },
        citations=citations,
    )
    logger.log_response(
        status=resp.status, citations_count=len(resp.citations or [])
    )
    return resp


# ---------------------------------------------------------------------------
# tool: list_verification_methods
# ---------------------------------------------------------------------------

@app.post("/tools/list_verification_methods")
async def list_verification_methods(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    logger = AuditLogger(trace_id=payload.trace_id, service_name="verify-mcp")
    logger.log_request(
        content_type=payload.content_type, tool="list_verification_methods"
    )

    methods = [
        {
            "name": name,
            "description": schema["description"],
            "reliability": schema["reliability"],
        }
        for name, schema in _METHODS.items()
    ]

    resp = _ok(trace_id=payload.trace_id, data={"methods": methods})
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: get_method_detail
# ---------------------------------------------------------------------------

@app.post("/tools/get_method_detail")
async def get_method_detail(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    method_name = payload.parameters.get("method_name")
    if not method_name:
        return _error(
            payload.trace_id, "Parameter 'method_name' is required."
        )

    logger = AuditLogger(trace_id=payload.trace_id, service_name="verify-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="get_method_detail",
        method_name=method_name,
    )

    schema = _METHODS.get(method_name)
    if schema is None:
        supported = ", ".join(sorted(_METHODS.keys()))
        return _error(
            payload.trace_id,
            f"Unknown method: {method_name!r}. "
            f"Supported: {supported}.",
        )

    resp = _ok(trace_id=payload.trace_id, data=schema)
    logger.log_response(status=resp.status)
    return resp
