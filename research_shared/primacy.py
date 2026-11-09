"""Primacy distance: how far is this claim from primary evidence (#254).

Ported from research-service `compute_observation_primacy_score`, which is the
spec the operator drafted. Four weighted components:

    score = 0.45*lineage + 0.25*mediated + 0.20*provenance + 0.10*grounding

Lineage dominates because a claim copied from a summary is weaker evidence than a
claim read out of the paper, whatever its wording. Source class and grounding
name what the text itself cannot.

Saimon shipped a stub that returned 1.0 for everything — all 1,081 observations
read `primary`. A constant is not a measurement.
"""

from __future__ import annotations

import re

PRIMACY_VERSION = "v1"

# Source class -> distance from primary evidence. Lower is closer.
SOURCE_CLASSES: dict[str, float] = {
    "document": 0.10,
    "dataset": 0.10,
    "government_report": 0.10,
    "journal_article": 0.25,
    "report": 0.25,
    "news": 0.45,
    "press_release": 0.45,
    "blog": 0.70,
    "social": 0.70,
    "forum_post": 0.70,
}
UNKNOWN_SOURCE_DISTANCE = 0.55
NO_PATH_LINEAGE_DISTANCE = 0.58

MEDIATED_MARKERS = (
    "according to",
    "reportedly",
    "analysts said",
    "it is believed",
    "suggests that",
    "population-based studies",
    "previous studies",
    "prior studies",
    "has been reported",
    "it was reported",
)
SUMMARY_MARKERS = ("summary", "overview", "in conclusion", "the report notes")

_TIER_BY_HOPS = {0: "direct", 1: "near_direct", 2: "mediated"}

# Bracket citations: "[12]" marks the claim as read from a secondary write-up.
_BRACKET_CITATION_RE = re.compile(r"\[\d{1,3}\]")


def source_class_from_host(host: str | None) -> str:
    """Classify a source by its host. Unknown hosts stay unknown, never direct."""
    if not host:
        return "unknown"
    host = host.lower().split("/")[0]
    if host.endswith((".gov", ".gov.uk", ".mil")):
        return "government_report"
    if any(domain in host for domain in (
        "arxiv.org", "acm.org", "ieee.org", "springer", "nature.com",
        "sciencedirect", "wiley.com", "tandfonline", "jstor", "pubmed",
    )):
        return "journal_article"
    if any(domain in host for domain in ("wikipedia.org", "w3.org", "ietf.org", "iso.org")):
        return "report"
    if any(domain in host for domain in ("medium.com", "substack.com", "blogspot", "wordpress.com")):
        return "blog"
    if any(domain in host for domain in ("reddit.com", "stackexchange", "forum")):
        return "forum_post"
    if any(domain in host for domain in ("reuters.com", "apnews.com", "bbc.", "nytimes.com")):
        return "news"
    return "unknown"


def source_distance(source_class: str | None) -> float:
    return SOURCE_CLASSES.get((source_class or "unknown").lower(), UNKNOWN_SOURCE_DISTANCE)


def mediated_distance(text: str, *, extraction_method: str | None = None) -> float:
    """How much the claim's own wording marks it as second-hand."""
    lowered = (text or "").lower()
    score = 0.0
    if any(marker in lowered for marker in MEDIATED_MARKERS):
        score += 0.45
    if any(marker in lowered for marker in SUMMARY_MARKERS):
        score += 0.35
    if (extraction_method or "").lower() in {"summary", "aggregation", "inference"}:
        score += 0.35
    if _BRACKET_CITATION_RE.search(text or ""):
        score += 0.20
    return round(min(score, 1.0), 4)


def grounding_distance(verification_status: str | None, confidence: float | None = None) -> float:
    """Distance contributed by the claim's grounding, not by its source."""
    status = (verification_status or "insufficient_evidence").strip().lower()
    conf = max(0.0, min(float(confidence or 0.0), 1.0))
    if status == "supported":
        return round(max(0.0, 0.15 - conf * 0.10), 4)
    if status == "contradicted":
        return 0.20
    if status == "mixed":
        return 0.28
    if status == "error":
        return 0.55
    return 0.40


def lineage_distance(hops: int | None) -> tuple[float, str]:
    """Distance from the nearest direct anchor; 0.58 when no path exists."""
    if hops is None:
        return NO_PATH_LINEAGE_DISTANCE, "no_path_to_direct_anchor"
    return round(min(hops / 3.0, 1.0), 4), "path_to_direct_anchor"


def tier_for(score: float | None, hops: int | None) -> str:
    """Tier from the score; ``direct`` is reserved for a zero-hop anchor.

    research-service derived the tier from the hop count alone, which works when
    the corpus contains real transformation chains. Saimon does not: every claim
    sits one hop from its document, so a hop-derived tier labelled 99% of 8,528
    nodes `near_direct` and carried no signal — a constant in a new costume.
    Hops still gate `direct` (only a zero-hop anchor qualifies); the bands decide
    the rest, and the hop count stays in the breakdown either way.
    """
    if score is None:
        return "unknown"
    if hops == 0:
        return "direct"
    if score <= 0.35:
        return "near_direct"
    if score <= 0.60:
        return "mediated"
    return "multi_hop"


def compute_primacy(
    *,
    text: str,
    source_class: str | None,
    hops: int | None,
    verification_status: str | None = None,
    confidence: float | None = None,
    extraction_method: str | None = None,
    has_context: bool = True,
) -> tuple[float | None, str, dict]:
    """Return (score, tier, breakdown). ``None`` with a reason when context is missing."""
    if not has_context:
        return None, "unknown", {
            "version": PRIMACY_VERSION,
            "status": "unknown",
            "reason": "missing_source_and_document_context",
        }

    lineage, lineage_status = lineage_distance(hops)
    mediated = mediated_distance(text, extraction_method=extraction_method)
    provenance = source_distance(source_class)
    grounding = grounding_distance(verification_status, confidence)

    score = (
        0.45 * lineage
        + 0.25 * mediated
        + 0.20 * provenance
        + 0.10 * grounding
    )
    bounded = round(max(0.0, min(score, 0.99)), 4)
    tier = tier_for(bounded, hops)
    return bounded, tier, {
        "version": PRIMACY_VERSION,
        "status": "computed",
        "lineage_status": lineage_status,
        "hops_to_direct_anchor": hops,
        "lineage_component": lineage,
        "mediated_language_component": mediated,
        "source_provenance_component": provenance,
        "source_class": (source_class or "unknown"),
        "grounding_component": grounding,
    }
