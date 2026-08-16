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
import os as _os
import re as _re
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

from mcp.verify.writing_continuity import (
    set_db_pool as set_writing_continuity_db_pool,
)
from mcp.verify.writing_continuity import (
    verify_against_kg,
)
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.hardening import apply_hardening, build_audit_logger
from research_shared.lifespan import build_lifespan
from research_shared.llm import LLMClient, LLMError

# ---------------------------------------------------------------------------
# backend injection (must be before lifespan)
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None
_db_pool: Any = None


def set_llm_client(client: LLMClient | None) -> None:
    """Inject an LLMClient for AI-powered fact-checking."""
    global _llm_client
    _llm_client = client


def set_db_pool(pool: Any | None) -> None:
    """Inject a DatabasePool for persisting verification results."""
    global _db_pool
    _db_pool = pool
    set_writing_continuity_db_pool(pool)


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan(
    "verify-mcp",
    llm_client_ref=lambda: _llm_client,
    llm_client_setter=set_llm_client,
    db_pool_ref=lambda: _db_pool,
    db_pool_setter=set_db_pool,
)
app = FastAPI(title="verify-mcp", version="0.1.0", lifespan=_lifespan)

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

# ── shadow source corroboration (configurable) ────────────────────

_SHADOW_SOURCES_ENABLED = _os.environ.get("SHADOW_SOURCES_ENABLED", "true").lower() in (
    "1", "true", "yes", "on",
)

if _SHADOW_SOURCES_ENABLED:
    _METHODS["shadow_source_corroboration"] = {
        "name": "shadow_source_corroboration",
        "description": (
            "Cross-reference the claim against paywalled academic sources "
            "accessible via shadow libraries (Sci-Hub, LibGen, Anna's Archive)."
        ),
        "reliability": 0.88,
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
            _log.debug("verify-mcp health: LLM not reachable", exc_info=True)
    observations_count = 0
    if _db_pool is not None:
        try:
            row = await _db_pool.fetch("SELECT count(*) as cnt FROM observations")
            observations_count = row[0]["cnt"] if row else 0
        except Exception:  # noqa: BLE001
            _log.debug("verify-mcp health: observations count query failed", exc_info=True)
    return {
        "status": "ok",
        "service": "verify-mcp",
        "checks": {
            "llm": "connected" if llm_ok else "unavailable",
            "observations_count": observations_count,
        },
    }


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
    {
        "name": "extract_claims",
        "description": "Extract falsifiable claims from source text with confidence scores.",
        "parameters": {
            "source_text": "str (required)",
            "max_claims": "int (optional, default 10)",
        },
    },
    {
        "name": "verify_against_kg",
        "description": (
            "Flag continuity breaks and character inconsistencies in a "
            "scene against a universe knowledge graph."
        ),
        "parameters": {
            "scene_text": "str (required)",
            "universe_id": "str (required)",
        },
    },
]


@app.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """Return the tool manifest for this MCP."""
    _require_auth(request)
    return {"tools": _TOOLS}


# ---------------------------------------------------------------------------
# tool: verify_against_kg (writing continuity)
# ---------------------------------------------------------------------------

@app.post("/tools/verify_against_kg")
async def verify_against_kg_tool(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    scene_text = payload.parameters.get("scene_text", "")
    universe_id = payload.parameters.get("universe_id")
    if not scene_text.strip():
        return _error(payload.trace_id, "Parameter 'scene_text' is required.")
    if not universe_id:
        return _error(payload.trace_id, "Parameter 'universe_id' is required.")

    findings = await verify_against_kg(scene_text, universe_id)
    return _ok(
        payload.trace_id,
        data={"findings": findings, "total": len(findings)},
    )


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

_SEARCH_MCP_URL = _os.environ.get("SEARCH_MCP_URL", "http://saimon-search:8001")
_SEARCH_API_KEY = _os.environ.get("SAIMON_API_KEY", "sk-test-search-key")

_VERIFY_PROMPT = """You are an expert fact-checker with access to shadow library
sources. Verify the following claim using these methods: {methods}.

CLAIM: {claim}

SOURCES FOUND VIA SHADOW LIBRARIES:
{sources_text}

For each method, analyze the claim against the sources above. If a source
directly supports or refutes the claim, cite it by title and DOI. Be precise.

Return ONLY a JSON object with:
- "verifications": array of {{"method": "...", "verdict": "supported|refuted|inconclusive", "confidence": 0.0-1.0, "explanation": "...", "evidence_source": "title or DOI or null"}}
- "overall_verdict": "supported|refuted|inconclusive"
"""


async def _search_sources(
    claim: str, limit: int = 5,
) -> list[dict[str, Any]]:
    """Search shadow libraries for sources relevant to the claim."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_SEARCH_MCP_URL}/tools/search_shadow_libraries",
                json={
                    "trace_id": "00000000-0000-0000-0000-000000000000",
                    "content_type": "search",
                    "parameters": {"query": claim, "limit": limit},
                },
                headers={"X-Saimon-API-Key": _SEARCH_API_KEY},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", {}).get("results", [])
    except Exception:  # noqa: BLE001, S110
        pass
    return []


def _format_sources(sources: list[dict[str, Any]]) -> str:
    """Format source results into a readable text block for the LLM."""
    if not sources:
        return "No sources found."
    lines = []
    for i, s in enumerate(sources, 1):
        title = s.get("title", "Unknown")
        source = s.get("source_index_label", s.get("source_index", "unknown"))
        doi = s.get("doi", "")
        authors = ", ".join(s.get("authors", [])[:3])
        year = s.get("year", "")
        lines.append(
            f"[{i}] {title}\n"
            f"    Authors: {authors or 'Unknown'} | Year: {year or 'Unknown'}\n"
            f"    Source: {source} | DOI: {doi or 'N/A'}"
        )
    return "\n\n".join(lines)


async def _llm_verify(
    method_names: list[str], claim: str, sources: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Verify a claim via the injected LLM with real source content."""
    sources_text = _format_sources(sources or [])
    prompt = _VERIFY_PROMPT.format(
        methods=", ".join(method_names),
        claim=claim,
        sources_text=sources_text,
    )
    raw = await _llm_client.generate(prompt)  # type: ignore[union-attr]
    result = _json.loads(raw)
    return result.get("verifications", [])


# ── citation verification ────────────────────────────────────────

_DOI_PATTERN = _re.compile(r"10\.\d{4,}/[^\s\"'<>]+", _re.IGNORECASE)


def _extract_dois(text: str) -> list[str]:
    """Extract DOI strings from text using a regex pattern."""
    return _DOI_PATTERN.findall(text)


async def _verify_citation(doi: str) -> dict[str, Any]:
    """Resolve a claimed DOI via _search_sources().

    Returns a dict with:
      - verified: bool
      - source: dict | None (matched source metadata if found)
      - flag: str | None ("[UNVERIFIED SOURCE]" if not found)
    """
    results = await _search_sources(f"doi:{doi}", limit=5)
    for result in results:
        result_doi = result.get("doi", "")
        if result_doi and result_doi.lower().strip() == doi.lower().strip():
            return {"verified": True, "source": result, "flag": None}
    return {
        "verified": False,
        "source": None,
        "flag": "[UNVERIFIED SOURCE]",
    }


async def _verify_citations_in_verifications(
    verifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Scan all verification explanations for DOIs and flag any that
    do not resolve."""
    updated: list[dict[str, Any]] = []
    for v in verifications:
        explanation = v.get("explanation", "")
        evidence_source = v.get("evidence_source", "")
        # Check evidence_source field for a DOI
        if evidence_source:
            dois = _extract_dois(evidence_source)
            for doi in dois:
                result = await _verify_citation(doi)
                if not result["verified"]:
                    explanation = (
                        f"{explanation} [UNVERIFIED SOURCE: {doi}]"
                    )
        # Also check explanation text for DOIs
        dois_in_explanation = _extract_dois(explanation)
        verified_dois: set[str] = set()
        for doi in dois_in_explanation:
            if doi in verified_dois:
                continue
            result = await _verify_citation(doi)
            if not result["verified"]:
                explanation = explanation.replace(
                    doi, f"{doi} [UNVERIFIED SOURCE]"
                )
            verified_dois.add(doi)
        updated.append({**v, "explanation": explanation})
    return updated


# ── DOI resolution (FACTUALITY-CITATION-1) ────────────────────


async def _resolve_doi(doi: str) -> dict[str, Any]:
    """Resolve a DOI via search MCP and return bibliographic metadata.

    Returns:
        dict with keys: found (bool), title (str), authors (list[str]),
        year (str|int).
    """
    results = await _search_sources(f"doi:{doi}", limit=5)
    for result in results:
        result_doi = result.get("doi", "")
        if result_doi and result_doi.lower().strip() == doi.lower().strip():
            return {
                "found": True,
                "title": result.get("title", ""),
                "authors": result.get("authors", []),
                "year": result.get("year", ""),
            }
    return {"found": False, "title": "", "authors": [], "year": ""}


def create_evidence_link(
    observation_id: str,
    source_identifier: str,
    excerpt: str = "",
    confidence: float = 0.5,
) -> dict[str, Any]:
    """Create an evidence link connecting observation → source.

    Each link carries an excerpt from the verification explanation,
    a confidence score, and a content hash for staleness detection.

    Returns:
        dict with keys: observation_id, source_identifier, excerpt,
        confidence, content_hash.
    """
    import hashlib
    content = f"{source_identifier}:{excerpt}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    return {
        "observation_id": observation_id,
        "source_identifier": source_identifier,
        "excerpt": excerpt,
        "confidence": confidence,
        "content_hash": content_hash,
    }


def check_citation_staleness(
    current_hash: str,
    previous_hash: str,
) -> dict[str, Any]:
    """Compare content_hash values to detect stale evidence.

    When a previously-verified source changes (hash mismatch),
    the evidence link is flagged as stale and should be re-verified.

    Returns:
        dict with keys: stale (bool), reason (str|None),
        current_hash (str), previous_hash (str).
    """
    if current_hash != previous_hash:
        return {
            "stale": True,
            "reason": "content_hash mismatch — source may have changed",
            "current_hash": current_hash,
            "previous_hash": previous_hash,
        }
    return {"stale": False, "reason": None}


async def _build_evidence_links(
    verifications: list[dict[str, Any]],
    observation_id: str = "",
) -> list[dict[str, Any]]:
    """Post-LLM DOI resolution pass.

    Scans every verification for a cited DOI in evidence_source,
    resolves it via _resolve_doi(), and creates an evidence_link
    for each verified claim → source pair.

    Unresolved DOIs are flagged with [UNVERIFIED SOURCE].

    Returns:
        list of evidence_link dicts.
    """
    evidence_links: list[dict[str, Any]] = []
    seen_dois: set[str] = set()

    for v in verifications:
        evidence_source = v.get("evidence_source", "")
        if not evidence_source:
            continue
        dois = _extract_dois(evidence_source)
        for doi in dois:
            if doi in seen_dois:
                continue
            seen_dois.add(doi)
            resolved = await _resolve_doi(doi)
            if resolved["found"]:
                excerpt = v.get("explanation", "")[:200]
                confidence: float = float(v.get("confidence", 0.5))
                link = create_evidence_link(
                    observation_id=observation_id,
                    source_identifier=f"doi:{doi}",
                    excerpt=excerpt,
                    confidence=confidence,
                )
                link["doi_meta"] = {
                    "title": resolved["title"],
                    "authors": resolved["authors"],
                    "year": resolved["year"],
                }
            else:
                link = {
                    "observation_id": observation_id,
                    "source_identifier": f"doi:{doi}",
                    "excerpt": "",
                    "confidence": 0.0,
                    "content_hash": "",
                    "flagged": True,
                    "flag_reason": "[UNVERIFIED SOURCE]",
                }
            evidence_links.append(link)

    return evidence_links


# ── adversarial verification ─────────────────────────────────────

_REFUTATION_PROMPT = """You are a skeptical fact-checker tasked with refuting a
claim.  Your job is to find flaws, counter-evidence, and weaknesses in the
claim, even if you personally believe it might be true.  Argue AGAINST the
claim using the sources provided.

CLAIM: {claim}

SOURCES:
{sources_text}

Return ONLY a JSON object with:
- "verifications": array of {{"method": "adversarial_review", "verdict": "supported|refuted|inconclusive", "confidence": 0.0-1.0, "explanation": "...", "key_objections": ["..."]}}
- "overall_verdict": "supported|refuted|inconclusive"
- "key_disagreements": ["..."]
"""


async def _llm_refute(
    claim: str, sources: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Run a second LLM call with a refutation (adversarial) prompt."""
    sources_text = _format_sources(sources or [])
    prompt = _REFUTATION_PROMPT.format(
        claim=claim,
        sources_text=sources_text,
    )
    raw = await _llm_client.generate(prompt)  # type: ignore[union-attr]
    return _json.loads(raw)


def _compare_adversarial(
    primary_verdict: str,
    adversarial_result: dict[str, Any],
) -> dict[str, Any]:
    """Compare primary and adversarial verdicts.  If they disagree,
    return a disputed flag with both perspectives."""
    adv_verdict = adversarial_result.get("overall_verdict", "inconclusive")
    adv_verifications = adversarial_result.get("verifications", [])
    disagreements = adversarial_result.get("key_disagreements", [])

    if primary_verdict != adv_verdict and primary_verdict != "inconclusive" and adv_verdict != "inconclusive":
        return {
            "disputed": True,
            "primary_perspective": primary_verdict,
            "adversarial_perspective": adv_verdict,
            "adversarial_verifications": adv_verifications,
            "key_disagreements": disagreements,
        }
    return {
        "disputed": False,
        "adversarial_verifications": adv_verifications,
    }


# ── confidence / abstention ──────────────────────────────────────


def _compute_overall_confidence(
    verifications: list[dict[str, Any]],
) -> float:
    """Compute the weighted-average confidence across all verifications."""
    if not verifications:
        return 0.0
    total_weight = 0.0
    weighted_confidence = 0.0
    for v in verifications:
        method_name = v.get("method", "")
        reliability = _METHODS.get(method_name, {}).get("reliability", 0.5)
        conf = v.get("confidence", 0.5)
        weighted_confidence += conf * reliability
        total_weight += reliability
    if total_weight == 0:
        return 0.0
    return round(weighted_confidence / total_weight, 2)


# ── risk profile helpers ─────────────────────────────────────────

_NAME_PATTERN = _re.compile(
    r"\b[A-Z][a-z]+ (?:van |de |von |del )?[A-Z][a-z]+\b"
)
_DATE_PATTERN = _re.compile(
    r"\b(?:\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4})\b"
)
_NUMBER_PATTERN = _re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?%?\b")


def _detect_risk_items(claim: str) -> dict[str, list[str]]:
    """Detect names, dates, numbers, and citation references in a claim."""
    return {
        "names": _NAME_PATTERN.findall(claim),
        "dates": _DATE_PATTERN.findall(claim),
        "numbers": _NUMBER_PATTERN.findall(claim),
        "citations": _DOI_PATTERN.findall(claim),
    }


def _build_risk_boosted_prompt(
    base_prompt: str, claim: str, risk_items: dict[str, list[str]]
) -> str:
    """Augment the verification prompt with high-risk item checking
    instructions when risk_profile='high'."""
    extras: list[str] = []
    if risk_items.get("names"):
        extras.append(
            f"- NAMES to verify: {', '.join(risk_items['names'][:5])}"
        )
    if risk_items.get("dates"):
        extras.append(
            f"- DATES to verify: {', '.join(risk_items['dates'][:5])}"
        )
    if risk_items.get("numbers"):
        extras.append(
            f"- NUMBERS to verify: {', '.join(risk_items['numbers'][:5])}"
        )
    if risk_items.get("citations"):
        extras.append(
            f"- CITATIONS/DOIs to verify: {', '.join(risk_items['citations'][:5])}"
        )
    if not extras:
        return base_prompt

    boost = (
        "\n\n⚠️ HIGH-RISK CHECK: The following specific items appear in the claim "
        "and MUST be individually verified against sources:\n"
        + "\n".join(extras)
        + "\n\nFor each item, explicitly state whether the sources confirm or contradict it."
    )
    return base_prompt + boost


# ── observation graph (FACTUALITY-OBSERVATION-1) ─────────────────

_EXTRACT_CLAIMS_PROMPT = """You are a claim extraction specialist. From the
source text below, extract all factual claims that are falsifiable — i.e.,
claims that could potentially be verified or refuted against external sources.

SOURCE TEXT:
{source_text}

For each claim, provide:
- "claim_text": the exact claim statement
- "topic": a short topic label (1-3 words)
- "confidence_0_1": your confidence (0.0-1.0) that this is a well-formed falsifiable claim
- "rationale": brief explanation of why this is falsifiable

Return ONLY a JSON object with:
- "claims": array of claim objects
- Do NOT include opinions, subjective statements, or unfalsifiable assertions.
- If the text contains no falsifiable claims, return an empty array.
"""


async def _llm_extract_claims(
    source_text: str, max_claims: int = 10,
) -> list[dict[str, Any]]:
    """Extract falsifiable claims from source text via LLM."""
    if not source_text.strip():
        return []
    prompt = _EXTRACT_CLAIMS_PROMPT.format(source_text=source_text)
    if max_claims > 0:
        prompt += f"\n\nExtract at most {max_claims} claims."
    raw = await _llm_client.generate(prompt)  # type: ignore[union-attr]
    result = _json.loads(raw)
    return result.get("claims", [])


def _compute_source_quality_tier(source: dict[str, Any]) -> str:
    """Compute source quality tier (A/B/C/unknown) from shadow library metadata.

    Tier A: peer-reviewed journal, high citation count
    Tier B: conference paper, moderate reputation
    Tier C: preprint, low reputation
    unknown: insufficient metadata
    """
    source_index = source.get("source_index_label", source.get("source_index", "")).lower()
    year = source.get("year")
    citations = source.get("citation_count", source.get("citations", 0))

    # Tier A indicators
    tier_a_indexes = {"scihub", "pubmed", "crossref", "scopus", "wos"}
    if source_index in tier_a_indexes:
        return "A"
    if isinstance(citations, (int, float)) and citations > 50:
        return "A"

    # Tier B indicators
    tier_b_indexes = {"libgen", "semantic_scholar", "dblp", "ieee"}
    if source_index in tier_b_indexes:
        return "B"
    if isinstance(year, (int, float)) and isinstance(citations, (int, float)) and citations > 10:
        return "B"

    # Tier C indicators
    tier_c_indexes = {"arxiv", "ssrn", "researchgate", "preprint"}
    if source_index in tier_c_indexes:
        return "C"
    if source.get("is_preprint") or source.get("preprint"):
        return "C"

    return "unknown"


def _compute_primacy_score(
    source: dict[str, Any] | None, relation_depth: int = 0,
) -> float:
    """Compute primacy distance score.

    direct source (original paper/data) = 1.0
    one-hop (review citing original)     = 0.7
    two-hop                               = 0.5
    unknown                               = 0.3
    """
    if source is None:
        return 0.3

    # If source appears to be primary research (has methods/data)
    is_primary = any(
        source.get(k) for k in (
            "has_methods", "has_data", "is_primary", "primary_source"
        )
    )
    if is_primary:
        return 1.0

    # Check source type
    source_type = source.get("type", source.get("source_type", "")).lower()
    if source_type in ("primary", "original_research", "dataset"):
        return 1.0
    if source_type in ("review", "meta_analysis", "survey"):
        score = 0.7 - 0.2 * relation_depth
        return round(max(0.3, score), 1)

    # Default: score by distance
    base = 1.0 - 0.3 * relation_depth
    return round(max(0.3, base), 1)


async def _persist_observation(
    claim: dict[str, Any],
    source_text: str = "",
    verification_node_id: str | None = None,
) -> str | None:
    """Persist a single observation to the observations table.

    Returns the observation UUID if persisted, None on failure.
    """
    if _db_pool is None:
        return None
    try:
        import hashlib as _hashlib
        import uuid as _uuid

        obs_id = str(_uuid.uuid4())
        source_hash = _hashlib.sha256(source_text.encode()).hexdigest()[:16] if source_text else None

        await _db_pool.execute(
            """INSERT INTO observations
               (id, claim_text, topic, summary, confidence_0_1, rationale,
                source_text_hash, primacy_distance_score)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            obs_id,
            claim.get("claim_text", ""),
            claim.get("topic"),
            claim.get("claim_text", "")[:200],
            float(claim.get("confidence_0_1", 0.5)),
            claim.get("rationale"),
            source_hash,
            1.0,  # default primacy for extracted claims
        )
        return obs_id
    except Exception:  # noqa: BLE001
        return None


async def _link_observation_verification(
    observation_id: str,
    verification_node_id: str,
    method: str,
    verdict: str,
    confidence: float,
    explanation: str = "",
) -> None:
    """Create an observation_verifications row linking obs to verification."""
    if _db_pool is None:
        return
    try:
        import uuid as _uuid
        ver_id = str(_uuid.uuid4())
        await _db_pool.execute(
            """INSERT INTO observation_verifications
               (id, observation_id, verification_id, method, verdict, confidence, explanation)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ver_id, observation_id, verification_node_id,
            method, verdict, confidence, explanation,
        )
    except Exception:  # noqa: BLE001, S110
        pass


async def _create_observation_relation(
    source_obs_id: str,
    target_obs_id: str,
    relation_type: str,
    label: str = "",
) -> None:
    """Create an edge between two observations."""
    if _db_pool is None:
        return
    try:
        await _db_pool.execute(
            """INSERT INTO observation_relations
               (source_id, target_id, relation_type, label)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (source_id, target_id, relation_type) DO NOTHING""",
            source_obs_id, target_obs_id, relation_type, label,
        )
    except Exception:  # noqa: BLE001, S110
        pass


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
            "verdict": "inconclusive",
            "confidence": 0.25,
            "explanation": (
                f"Could not cross-reference claim '{claim[:60]}...' "
                f"against {source_count} sources. "
                "LLM backend not available — stub returns inconclusive. "
                "Set DEEPSEEK_API_KEY and inject an LLMClient for "
                "real source corroboration."
            ),
        },
        "logical_consistency": lambda: {
            "verdict": "inconclusive",
            "confidence": 0.25,
            "explanation": (
                f"Could not assess logical consistency of "
                f"'{claim[:60]}...'. "
                "LLM backend not available — stub returns inconclusive. "
                "Set DEEPSEEK_API_KEY and inject an LLMClient for "
                "real logical analysis."
            ),
        },
        "authority_check": lambda: {
            "verdict": "inconclusive",
            "confidence": 0.25,
            "explanation": (
                f"Could not verify '{claim[:60]}...' against "
                "authoritative sources. "
                "LLM backend not available — stub returns inconclusive. "
                "Set DEEPSEEK_API_KEY and inject an LLMClient for "
                "real authority checking."
            ),
        },
        "temporal_validity": lambda: {
            "verdict": "inconclusive",
            "confidence": 0.25,
            "explanation": (
                f"Could not check temporal validity of "
                f"'{claim[:60]}...'. "
                "LLM backend not available — stub returns inconclusive. "
                "Set DEEPSEEK_API_KEY and inject an LLMClient for "
                "real temporal validation."
            ),
        },
        "shadow_source_corroboration": lambda: {
            "verdict": "inconclusive",
            "confidence": 0.25,
            "explanation": (
                f"Could not cross-reference claim '{claim[:60]}...' "
                "against shadow library sources (Sci-Hub, LibGen, "
                "Anna's Archive). "
                "LLM backend not available — stub returns inconclusive. "
                "Set DEEPSEEK_API_KEY and inject an LLMClient for "
                "real shadow source corroboration."
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
        # Accept comma-separated string, JSON-encoded list, or Python list
        if isinstance(requested, str):
            import json as _json
            try:
                parsed = _json.loads(requested)
                if isinstance(parsed, list):
                    requested = parsed
                else:
                    requested = [m.strip() for m in requested.split(",") if m.strip()]
            except (_json.JSONDecodeError, ValueError):
                requested = [m.strip() for m in requested.split(",") if m.strip()]
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

    # ── shadow source search ─────────────────────────────────
    use_shadow = payload.parameters.get("use_shadow_sources", False)
    shadow_results: list[dict[str, Any]] = []
    if use_shadow:
        try:
            shadow_results = await _search_sources(claim, limit=5)
        except Exception:  # noqa: BLE001, S110
            pass  # degraded — continue without shadow sources

    logger = build_audit_logger(payload, request, _auth, "verify-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="verify_claim",
        claim_length=len(claim),
        methods_count=len(method_names),
        shadow_sources_found=len(shadow_results),
    )

    # ── risk profile: detect items for boosted checking ─────
    risk_profile = payload.parameters.get("risk_profile", "standard")
    risk_items: dict[str, list[str]] = {}
    if risk_profile == "high":
        risk_items = _detect_risk_items(claim)

    # Verify using each method — try LLM first, fall back to heuristic
    if _llm_client is not None:
        try:
            # Build risk-boosted prompt if needed
            sources_for_verify: list[dict[str, Any]] | None = (
                shadow_results if shadow_results else sources
            )
            if risk_profile == "high" and sources_for_verify:
                # Re-run _llm_verify with boosted prompt via a manual approach
                sources_text = _format_sources(sources_for_verify or [])
                base_prompt = _VERIFY_PROMPT.format(
                    methods=", ".join(method_names),
                    claim=claim,
                    sources_text=sources_text,
                )
                boosted_prompt = _build_risk_boosted_prompt(
                    base_prompt, claim, risk_items
                )
                raw = await _llm_client.generate(boosted_prompt)  # type: ignore[union-attr]
                result = _json.loads(raw)
                verifications = result.get("verifications", [])
            else:
                verifications = await _llm_verify(
                    method_names, claim, shadow_results if shadow_results else sources
                )
        except (LLMError, NotImplementedError, _json.JSONDecodeError):
            verifications = [
                _verify_method(m, claim, sources) for m in method_names
            ]
    else:
        verifications = [
            _verify_method(m, claim, sources) for m in method_names
        ]

    # ── citation verification ───────────────────────────────
    verify_citations = payload.parameters.get("verify_citations", False)
    if verify_citations:
        try:
            verifications = await _verify_citations_in_verifications(verifications)
        except Exception:  # noqa: BLE001, S110
            pass  # citation check is best-effort

    # ── adversarial verification ────────────────────────────
    adversarial = payload.parameters.get("adversarial", False)
    adversarial_result: dict[str, Any] | None = None
    if adversarial and _llm_client is not None:
        try:
            adversarial_result = await _llm_refute(
                claim, shadow_results if shadow_results else sources
            )
        except (LLMError, NotImplementedError, _json.JSONDecodeError):
            adversarial_result = None

    # Compute overall verdict
    overall = _compute_overall_verdict(verifications)
    overall_confidence = _compute_overall_confidence(verifications)

    # ── adversarial comparison ──────────────────────────────
    dispute_info: dict[str, Any] | None = None
    if adversarial_result is not None:
        dispute_info = _compare_adversarial(overall, adversarial_result)

    # ── abstention check ────────────────────────────────────
    abstained = overall_confidence < 0.5
    if abstained:
        overall = "inconclusive"

    # ── persist verification to knowledge graph ──────────────
    verification_node_id: str | None = None
    obs_id: str = ""
    if _db_pool is not None:
        try:
            import uuid as _uuid

            title = f"Verification: {claim[:80]}"
            # Check for existing verification of the same claim
            existing = await _db_pool.fetchrow(
                "SELECT id FROM knowledge_graph_nodes WHERE title = $1 LIMIT 1",
                title,
            )
            if existing is None:
                node_id = str(_uuid.uuid4())
                verification_node_id = node_id
                await _db_pool.execute(
                    "INSERT INTO knowledge_graph_nodes (id, title, content_type, body, metadata) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    node_id,
                    title,
                    "research_note",
                    _json.dumps({
                        "claim": claim,
                        "verdict": overall,
                        "verifications": verifications,
                        "shadow_results_count": len(shadow_results),
                    }),
                    _json.dumps({
                        "source": "verify-mcp",
                        "methods_used": method_names,
                        "shadow_sources": bool(shadow_results),
                    }),
                )
            else:
                verification_node_id = existing["id"]

            # ── persist as observation ─────────────────────────
            obs_claim = {
                "claim_text": claim,
                "topic": (method_names[0] if method_names else "verification"),
                "confidence_0_1": overall_confidence,
                "rationale": f"Verified via {', '.join(method_names)}",
            }
            obs_id = await _persist_observation(obs_claim, source_text=claim)

            # Update observation with verification status
            if obs_id:
                await _db_pool.execute(
                    "UPDATE observations SET verification_status = $1, "
                    "updated_at = now() WHERE id = $2",
                    "verified" if overall != "inconclusive" else "unverified",
                    obs_id,
                )

            # ── link observation to verifications ──────────────
            if obs_id and verification_node_id:
                for v in verifications:
                    await _link_observation_verification(
                        obs_id, verification_node_id,
                        v.get("method", "unknown"),
                        v.get("verdict", "inconclusive"),
                        v.get("confidence", 0.5),
                        v.get("explanation", ""),
                    )

            # ── compute source quality from shadow results ─────
            if obs_id and shadow_results:
                quality_tiers = [
                    _compute_source_quality_tier(s) for s in shadow_results
                ]
                best_tier = "unknown"
                for tier in ("A", "B", "C"):
                    if tier in quality_tiers:
                        best_tier = tier
                        break
                tier_scores = {"A": 0.9, "B": 0.7, "C": 0.5, "unknown": 0.3}
                await _db_pool.execute(
                    "UPDATE observations SET source_quality_tier = $1, "
                    "source_quality_score = $2, updated_at = now() WHERE id = $3",
                    best_tier, tier_scores[best_tier], obs_id,
                )

                # Compute primacy from best source
                best_source = shadow_results[0] if shadow_results else None
                primacy = _compute_primacy_score(best_source)
                primacy_tier = (
                    "primary" if primacy >= 0.8
                    else "secondary" if primacy >= 0.5
                    else "tertiary"
                )
                await _db_pool.execute(
                    "UPDATE observations SET primacy_distance_score = $1, "
                    "primacy_tier = $2, updated_at = now() WHERE id = $3",
                    primacy, primacy_tier, obs_id,
                )

            # ── create supporting relations between observations ──
            if obs_id and shadow_results:
                for sr in shadow_results[:3]:
                    sr_doi = sr.get("doi", "")
                    if sr_doi:
                        # Find existing observations with same source
                        existing_obs = await _db_pool.fetch(
                            "SELECT id FROM observations WHERE metadata->>'doi' = $1 LIMIT 3",
                            sr_doi,
                        )
                        for eo in existing_obs:
                            await _create_observation_relation(
                                obs_id, eo["id"], "related", "shared_source"
                            )

            # Update metadata with observation_id
            if obs_id and verification_node_id:
                await _db_pool.execute(
                    "UPDATE knowledge_graph_nodes "
                    "SET metadata = metadata || $1 WHERE id = $2",
                    _json.dumps({"observation_id": obs_id}),
                    verification_node_id,
                )

                # Store shadow source evidence
                import uuid as _obs_uuid
                for sr in shadow_results[:5]:
                    sr_doi = sr.get("doi", "")
                    sr_title = sr.get("title", "")
                    if sr_doi and sr_title:
                        await _db_pool.execute(
                            """INSERT INTO observation_verification_evidence
                               (id, verification_id, evidence_type, evidence_identifier, relevance_score, metadata)
                               VALUES ($1, $2, $3, $4, $5, $6)
                               ON CONFLICT DO NOTHING""",
                            str(_obs_uuid.uuid4()),
                            verification_node_id,
                            "shadow_source",
                            sr_doi,
                            0.7,
                            _json.dumps({"title": sr_title, "source_index": sr.get("source_index", "")}),
                        )

        except Exception:  # noqa: BLE001, S110
            pass  # KG write is best-effort

    # ── evidence links (FACTUALITY-CITATION-1) ───────────────
    evidence_links: list[dict[str, Any]] = []
    if verify_citations:
        try:
            evidence_links = await _build_evidence_links(
                verifications, observation_id=obs_id or ""
            )
        except Exception:  # noqa: BLE001, S110
            pass  # evidence links are best-effort

    citations = [
        r.get("doi") or r.get("identifier", "")
        for r in shadow_results
    ] if shadow_results else (
        [s.identifier for s in payload.sources] if payload.sources else []
    )

    resp_data: dict[str, Any] = {
        "verifications": verifications,
        "overall_verdict": overall,
        "overall_confidence": overall_confidence,
        "methods_used": len(verifications),
    }
    if abstained:
        resp_data["abstained"] = True
    if dispute_info is not None:
        resp_data["adversarial"] = dispute_info
    if risk_profile == "high":
        resp_data["risk_profile"] = "high"
        resp_data["risk_items_detected"] = {
            k: v for k, v in risk_items.items() if v
        }
    if evidence_links:
        resp_data["evidence_links"] = evidence_links

    resp = _ok(
        trace_id=payload.trace_id,
        data=resp_data,
        citations=citations,
    )
    logger.log_response(
        status=resp.status, citations_count=len(resp.citations or [])
    )
    return resp


# ---------------------------------------------------------------------------
# tool: extract_claims
# ---------------------------------------------------------------------------

@app.post("/tools/extract_claims")
async def extract_claims(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    source_text = payload.parameters.get("source_text")
    if not source_text or not str(source_text).strip():
        return _error(
            payload.trace_id,
            "Parameter 'source_text' is required and must be non-empty.",
        )

    max_claims = int(payload.parameters.get("max_claims", 10))

    logger = build_audit_logger(payload, request, _auth, "verify-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="extract_claims",
        text_length=len(str(source_text)),
        max_claims=max_claims,
    )

    # Extract claims via LLM, fall back to empty list
    claims: list[dict[str, Any]] = []
    if _llm_client is not None:
        try:
            claims = await _llm_extract_claims(str(source_text), max_claims)
        except (LLMError, NotImplementedError, _json.JSONDecodeError):
            claims = []
    else:
        # Heuristic fallback: return empty (no LLM available)
        claims = []

    # ── persist extracted claims as observations ────────────
    observation_ids: list[str] = []
    if _db_pool is not None and claims:
        for claim in claims:
            obs_id = await _persist_observation(
                claim, source_text=str(source_text)
            )
            if obs_id:
                observation_ids.append(obs_id)

        # ── create relations between claims from same source ──
        if len(observation_ids) > 1:
            for i in range(len(observation_ids)):
                for j in range(i + 1, len(observation_ids)):
                    await _create_observation_relation(
                        observation_ids[i],
                        observation_ids[j],
                        "related",
                        "same_source",
                    )

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "claims": claims,
            "count": len(claims),
            "observation_ids": observation_ids if observation_ids else None,
        },
    )
    logger.log_response(status=resp.status, claims_count=len(claims))
    return resp


# ---------------------------------------------------------------------------
# tool: list_verification_methods
# ---------------------------------------------------------------------------

@app.post("/tools/list_verification_methods")
async def list_verification_methods(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    logger = build_audit_logger(payload, request, _auth, "verify-mcp")
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

    logger = build_audit_logger(payload, request, _auth, "verify-mcp")
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
