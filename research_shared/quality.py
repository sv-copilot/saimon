"""Observation and source quality scores (#255).

Primacy asks *how far is this from primary evidence*. Quality asks a different
question: *how much should I trust this row*. A blog post can be near-primary
(a first-hand account) and still be low quality; a peer-reviewed review is far
from primary and highly reliable. Keeping them separate is the whole point, so
they never share a column or a rank term.

Formulas ported from research-service (phase 5.1-5.2):

    observation = 0.45*extraction + 0.30*verification + 0.20*reputation + 0.05*structure
    source      = 0.42*reputation + 0.33*mean(observation) + 0.10*verification health
                  + 0.10*extraction health + 0.05*relation balance

Every score carries a version and a component breakdown, so a ranking can be
explained rather than asserted.
"""

from __future__ import annotations

QUALITY_VERSION = "v1"

REPUTATION_SCORES = {"A": 0.90, "B": 0.75, "C": 0.55, "unknown": 0.45}
DEFAULT_REPUTATION = 0.45

# How each verification outcome contributes to quality. A contradicted claim is
# not worthless (it tells you something), but it must not outrank a supported one.
VERIFICATION_QUALITY = {
    "supported": 1.00,
    "mixed": 0.50,
    "insufficient_evidence": 0.30,
    "contradicted": 0.15,
    "error": 0.00,
}
DEFAULT_VERIFICATION = 0.30

MAX_SCORE = 0.99

# A score built mostly from defaults is not a measurement. These are the minimum
# shares of claims that must carry real inputs before a backfill is allowed to
# write scores at all.
MIN_VERIFICATION_COVERAGE = 0.50
MIN_EXTRACTION_COVERAGE = 0.50


def is_scoreable(*, verification_coverage: float, extraction_coverage: float) -> tuple[bool, str]:
    """Whether a corpus has enough real inputs for quality scores to mean anything."""
    if verification_coverage < MIN_VERIFICATION_COVERAGE:
        return False, f"verification_coverage {verification_coverage:.0%} < {MIN_VERIFICATION_COVERAGE:.0%}"
    if extraction_coverage < MIN_EXTRACTION_COVERAGE:
        return False, f"extraction_coverage {extraction_coverage:.0%} < {MIN_EXTRACTION_COVERAGE:.0%}"
    return True, "ok"


def reputation_score(tier: str | None) -> float:
    return REPUTATION_SCORES.get((tier or "unknown").upper(), DEFAULT_REPUTATION)


def verification_score(status: str | None) -> float:
    return VERIFICATION_QUALITY.get((status or "").lower(), DEFAULT_VERIFICATION)


def structure_score(*, has_value: bool, has_date: bool, has_unit: bool) -> float:
    """Structured evidence is easier to check, so it scores higher."""
    present = sum((has_value, has_date, has_unit))
    return {0: 0.30, 1: 0.60, 2: 0.85, 3: 1.00}[present]


def extraction_score(confidence: float | None, *, low_signal: bool = False) -> float:
    if confidence is None or confidence <= 0:
        return 0.10 if low_signal else 0.55
    return max(0.0, min(float(confidence), 1.0))


def observation_quality(
    *,
    extraction: float,
    verification: float,
    reputation: float,
    structure: float,
) -> tuple[float, dict]:
    score = (
        0.45 * extraction
        + 0.30 * verification
        + 0.20 * reputation
        + 0.05 * structure
    )
    bounded = round(max(0.0, min(score, MAX_SCORE)), 4)
    return bounded, {
        "version": QUALITY_VERSION,
        "extraction_component": round(extraction, 4),
        "verification_component": round(verification, 4),
        "reputation_component": round(reputation, 4),
        "structure_component": round(structure, 4),
    }


def relation_balance(supporting: int, dissenting: int) -> float:
    """Bounded support-minus-dissent ratio; 0.5 when there is no evidence either way."""
    total = supporting + dissenting
    if total == 0:
        return 0.5
    # Clamp the RATIO to [-1, 1] before mapping it, not the scaled value: clamping
    # after the +0.5 shift made total dissent indistinguishable from neutrality.
    ratio = max(-1.0, min((supporting - dissenting) / total, 1.0))
    return round(ratio * 0.5 + 0.5, 4)


def source_quality(
    *,
    reputation: float,
    mean_observation: float,
    verification_health: float,
    extraction_health: float,
    balance: float,
) -> tuple[float, dict]:
    score = (
        0.42 * reputation
        + 0.33 * mean_observation
        + 0.10 * verification_health
        + 0.10 * extraction_health
        + 0.05 * balance
    )
    bounded = round(max(0.0, min(score, MAX_SCORE)), 4)
    return bounded, {
        "version": QUALITY_VERSION,
        "reputation_component": round(reputation, 4),
        "observation_component": round(mean_observation, 4),
        "verification_health_component": round(verification_health, 4),
        "extraction_health_component": round(extraction_health, 4),
        "relation_balance_component": round(balance, 4),
    }
