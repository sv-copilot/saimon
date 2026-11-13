"""Verification status algebra (SAIMON-VERIFY-EVIDENCE-ALGEBRA-1).

Ported from research-service: evidence counts map to a status with explicit
confidence floors and ceilings, and every status carries a human summary. The
point is that a verdict is a function of evidence — not of how plausible the
claim sounds.
"""

from __future__ import annotations

SUPPORTED = "supported"
MIXED = "mixed"
CONTRADICTED = "contradicted"
INSUFFICIENT = "insufficient_evidence"

SUPPORTED_FLOOR = 0.65
CONTRADICTED_FLOOR = 0.35
MIXED_FACTOR = 0.8
MAX_CONFIDENCE = 0.99


def resolve_status(
    *, supporting: int, contradicting: int, confidence: float
) -> tuple[str, float, str]:
    """Map evidence counts to (status, confidence, summary)."""
    if contradicting and supporting:
        status = MIXED
    elif contradicting:
        status = CONTRADICTED
        confidence = max(confidence, CONTRADICTED_FLOOR)
    elif supporting:
        status = SUPPORTED
        confidence = max(confidence, SUPPORTED_FLOOR)
    else:
        status = INSUFFICIENT

    confidence = min(max(confidence, 0.0), MAX_CONFIDENCE) if confidence else 0.0
    if status == SUPPORTED:
        summary = (
            f"Grounded in {supporting} corpus passage(s); the strongest shares the "
            "claim's distinctive terms."
        )
    elif status == MIXED:
        summary = (
            f"Found {supporting} supporting and {contradicting} contradicting passage(s); "
            "the evidence is not decisive."
        )
    elif status == CONTRADICTED:
        summary = f"{contradicting} passage(s) contradict the claim; it is not supported by the corpus."
    else:
        summary = (
            "No corpus passage supports this claim. Reported as insufficient evidence "
            "rather than guessed."
        )
    return status, round(confidence, 4), summary


def counts(evidence: list[dict]) -> tuple[int, int, int]:
    """(supporting, contradicting, mentions) — polarity is per item now.

    Until #347 every item was labelled `supports` by construction, so counting
    "not contradicts" as supporting made `contradicted` unreachable.
    """
    supporting = sum(1 for item in evidence if item.get("polarity") == "supports")
    contradicting = sum(1 for item in evidence if item.get("polarity") == "contradicts")
    mentions = len(evidence) - supporting - contradicting
    return supporting, contradicting, mentions


def ledger(evidence: list[dict], status: str, confidence: float) -> dict:
    """Counts plus per-item evidence, so a verdict can be audited."""
    supporting, contradicting, mentions = counts(evidence)
    return {
        "overall_verdict": status,
        "overall_confidence": confidence,
        "counts": {
            "evidence": len(evidence),
            "supporting": supporting,
            "contradicting": contradicting,
            "mentions": mentions,
            "abstained": 1 if status == INSUFFICIENT else 0,
        },
        "evidence": evidence,
    }
