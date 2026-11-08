"""Deterministic claim-candidate scoring (SAIMON-CLAIM-CANDIDATE-GATE-1).

The crew LLM is good at phrasing a claim and bad at knowing whether a sentence
is one. This module scores candidates before/after the model on structure alone —
verbs, numbers, units, time anchors, name lists, noise sections — and returns the
reasons, so a rejection is explainable instead of silent.

Ported from research-service (`knowledge_service._claim_candidate_score` +
`_claim_candidate_diagnostics`), whose weights are a starting point rather than
truth: the golden claim rubric in #248 is the instrument for tuning them.
"""

from __future__ import annotations

import re

DEFAULT_ACCEPT_THRESHOLD = 0.6

_CLAIM_VERB_RE = re.compile(
    r"\b(is|are|was|were|be|been|has|have|had|do|does|did|can|could|will|would|"
    r"report|reports|reported|show|shows|showed|find|finds|found|take|takes|took|"
    r"degrade|degrades|drop|drops|increase|increases|decrease|decreases|reduce|reduces|"
    r"handle|handled|require|requires|produce|produces|use|uses|contain|contains|"
    r"cost|costs|earn|earns|spend|spends|employ|employs|account|accounts|"
    r"rose|rise|rises|fell|fall|falls|grew|grow|grows)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d")
_UNIT_RE = re.compile(
    r"\b(%|percent|minute|minutes|hour|hours|day|days|week|weeks|month|months|"
    r"year|years|request|requests|dollar|dollars|usd|eur|kg|km|ms|seconds?)\b",
    re.IGNORECASE,
)
_TIME_ANCHOR_RE = re.compile(
    r"\b(q[1-4]|quarter|year|years|month|months|week|weeks|20\d{2}|19\d{2})\b",
    re.IGNORECASE,
)
_LEADER_RE = re.compile(r"\.{4,}")
_NOISE_SECTION_RE = re.compile(
    r"^(chapter|section|part|appendix|contents|table of contents|figure|table|"
    r"acknowledg|references|bibliography|index)\b",
    re.IGNORECASE,
)


def _tokens(text: str) -> list[str]:
    return text.split()


def looks_like_name_list(text: str) -> bool:
    """True for 'Smith, Jones, Alvarez' style bylines, which are not claims."""
    stripped = " ".join((text or "").split()).strip()
    if not stripped or _NUMBER_RE.search(stripped) or "," not in stripped:
        return False
    if _CLAIM_VERB_RE.search(stripped):
        return False
    segments = [seg.strip() for seg in stripped.replace("*", "").split(",") if seg.strip()]
    if len(segments) < 2:
        return False
    name_like = 0
    for segment in segments:
        words = [w for w in segment.replace(".", " ").split() if w]
        if not words or len(words) > 4:
            continue
        if all(w[:1].isupper() and w.replace("-", "").isalpha() for w in words):
            name_like += 1
    return name_like >= 2 and name_like / len(segments) >= 0.6


def score_claim_candidate(text: str) -> tuple[float, list[str]]:
    """Score a candidate claim in [0, ~2] and return the reasons for the score."""
    candidate = " ".join((text or "").split()).strip()
    if not candidate:
        return 0.0, ["Empty candidate"]

    score = 0.0
    reasons: list[str] = []

    token_count = len(_tokens(candidate))
    if token_count >= 8:
        score += 0.4
        reasons.append("At least 8 tokens")
    elif token_count < 4:
        score -= 0.5
        reasons.append("Too short to be a falsifiable claim")
    if _CLAIM_VERB_RE.search(candidate):
        score += 0.45
        reasons.append("Contains a claim verb")
    if _NUMBER_RE.search(candidate):
        score += 0.65
        reasons.append("Contains numeric evidence")
    if _UNIT_RE.search(candidate):
        score += 0.45
        reasons.append("Contains an explicit unit")
    if candidate[:1].isupper() and candidate.rstrip().endswith((".", "!", "?")):
        score += 0.2
        reasons.append("Complete sentence")
    if _TIME_ANCHOR_RE.search(candidate):
        score += 0.25
        reasons.append("Contains a time anchor")
    if looks_like_name_list(candidate):
        score -= 1.2
        reasons.append("Looks like a name list, not a claim")
    if _NOISE_SECTION_RE.match(candidate):
        score -= 1.0
        reasons.append("Matches a structural/noise section heading")
    if _LEADER_RE.search(candidate):
        score -= 1.0
        reasons.append("Contains dot leaders (table of contents)")
    if candidate[:1].islower():
        score -= 0.3
        reasons.append("Starts mid-sentence")

    return round(score, 4), reasons


def is_claim_candidate(text: str, threshold: float = DEFAULT_ACCEPT_THRESHOLD) -> bool:
    score, _ = score_claim_candidate(text)
    return score >= threshold
