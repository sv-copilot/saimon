"""crew.extract_claims@v1 — claim extraction (SAIMON-CREW-CLAIM-EXTRACT-1).

Extracts falsifiable, time-anchored claim candidates from source text via the
crew LLM (saimon.extract_claims → mechanical/flash), then runs them through a
quality gate that excludes bylines/headings/ToC and clamps confidence to [0, 1].
Pure helpers are unit-testable without CrewAI or a network.
"""

from __future__ import annotations

import json as _json
import logging as _logging
import os
import re as _re
from typing import Any

from research_shared.claims import DEFAULT_ACCEPT_THRESHOLD, score_claim_candidate
from saimon_mcp.crew.llm import make_crew_llm

_log = _logging.getLogger("saimon.crew.claim_extract")

_EXTRACT_PROMPT = """You are a claim extraction specialist. From the source
text below, extract all factual claims that are falsifiable — i.e., claims that
could potentially be verified or refuted against external sources. Exclude
bylines, headings, table-of-contents lines, and other non-claim scaffolding.

SOURCE TEXT:
{source_text}

For each claim, provide:
- "claim_text": the exact claim statement
- "topic": a short topic label (1-3 words)
- "confidence_0_1": your confidence (0.0-1.0) that this is a well-formed falsifiable claim
- "rationale": brief explanation of why this is falsifiable

Return ONLY a JSON object with:
- "claims": array of claim objects
If the text contains no falsifiable claims, return an empty array.
"""

_STRUCTURAL_PREFIX = _re.compile(
    r"^(chapter|section|part|appendix|contents|table of contents|"
    r"figure|table|acknowledg|references|bibliography|index)\b",
    _re.IGNORECASE,
)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a value to [low, high]; non-numeric falls back to low."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


def _looks_structural(claim_text: str) -> bool:
    """True if a claim candidate looks like a byline/heading/ToC line."""
    text = (claim_text or "").strip()
    if not text or len(text) < 12:
        return True
    return bool(_STRUCTURAL_PREFIX.match(text))


def filter_crew_claim_candidates(candidates: list[dict]) -> list[dict]:
    """Quality gate: drop structural/malformed candidates, clamp confidence."""
    out: list[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        claim_text = (candidate.get("claim_text") or "").strip()
        if _looks_structural(claim_text):
            continue
        out.append(
            {
                "claim_text": claim_text,
                "topic": candidate.get("topic", ""),
                "confidence_0_1": _clamp(candidate.get("confidence_0_1")),
                "rationale": candidate.get("rationale", ""),
            }
        )
    return out


def parse_claims(raw: str) -> list[dict]:
    """Defensively parse the LLM JSON; never raises."""
    try:
        parsed = _json.loads(raw)
    except _json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    claims = parsed.get("claims")
    if not isinstance(claims, list):
        return []
    return filter_crew_claim_candidates(claims)


async def run_extract_claims(source_text: str, max_claims: int = 10) -> list[dict]:
    """Extract + filter claim candidates, fail-closed.

    The ``crew.extract_claims@v1`` tool contract resolves the declared
    ``saimon.extract_claims`` route. On LLM unavailability the real cause is
    logged (the claims response has no channel for a reason).
    """
    if not source_text.strip():
        return []

    resolved = make_crew_llm("saimon.extract_claims")
    if resolved.llm is None:
        _log.warning("crew LLM unavailable for extract_claims: %s", resolved.reason)
        return []

    prompt = _EXTRACT_PROMPT.format(source_text=source_text)
    if max_claims > 0:
        prompt += f"\n\nExtract at most {max_claims} claims."
    try:
        raw = resolved.llm.call([{"role": "user", "content": prompt}])
    except Exception:  # noqa: BLE001 — fail-closed, never crash
        return []

    threshold = float(
        os.getenv("SAIMON_CLAIM_MIN_SCORE", str(DEFAULT_ACCEPT_THRESHOLD))
    )
    accepted: list[dict] = []
    for claim in parse_claims(str(raw)):
        score, reasons = score_claim_candidate(claim.get("claim_text", ""))
        claim["score"] = score
        claim["reasons"] = reasons
        if score >= threshold:
            accepted.append(claim)
    return accepted
