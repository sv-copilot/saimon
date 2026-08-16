"""weighting.py — persuasive-authority weighting model (slice #71).

Domain-specific scoring exposed through ``LegalPlugin.weighting_models()``.
The mechanism is generic (a dict of callables) but the factors are legal:
persuasive authority is the weighted sum

    hierarchy x 0.35 + density x 0.25 + recency x 0.15 + fit x 0.15
    + treatment x 0.10

Every factor is a pure, bounded (0..1) function over case + jurisdiction
inputs, so the combined score is itself bounded to ``[0, 1]``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from plugins.legal.adapters.base import parse_year

#: Fixed factor weights — must sum to exactly 1.0.
WEIGHTS: dict[str, float] = {
    "hierarchy": 0.35,
    "density": 0.25,
    "recency": 0.15,
    "fit": 0.15,
    "treatment": 0.10,
}

#: Recency decays linearly to zero over this many years.
_RECENCY_WINDOW_YEARS = 40.0

#: Inbound-citation count at which ``density`` saturates at 1.0.
_DENSITY_SATURATION = 100.0

#: Same-jurisdiction bonus added to a court's base hierarchy score.
_SAME_JURISDICTION_BONUS = 0.1

#: Canonical reconciliation states mapped to a persuasive-authority contribution.
_TREATMENT_SCORES: dict[str, float] = {
    "STRONG_GREEN": 1.0,
    "WEAK_GREEN": 0.75,
    "YELLOW": 0.5,
    "RESURRECTION": 0.4,
    "MARKET_RED": 0.25,
    "CITATOR_RED": 0.0,
}

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "case",
        "court",
        "for",
        "in",
        "of",
        "on",
        "or",
        "states",
        "the",
        "to",
        "united",
        "v",
        "vs",
    }
)


# ---------------------------------------------------------------------------
# factors
# ---------------------------------------------------------------------------


def hierarchy(court: str, target_jurisdiction: str) -> float:
    """Score how persuasive *court* is in *target_jurisdiction* (0..1).

    Base score comes from the court's level (U.S. Supreme Court > federal
    circuit > state supreme > state appellate > district), plus a small bonus
    when the court sits in the target jurisdiction.  Capped at 1.0.
    """
    base = _court_level(court)
    if _same_jurisdiction(court, target_jurisdiction):
        base += _SAME_JURISDICTION_BONUS
    return min(1.0, base)


def density(case: dict[str, Any]) -> float:
    """Score citation density: inbound citations saturating at 100."""
    meta = case.get("metadata", {}) if isinstance(case, dict) else {}
    count = case.get("citation_count", meta.get("citation_count", 0))
    try:
        value = float(count)
    except (TypeError, ValueError):
        value = 0.0
    return min(1.0, value / _DENSITY_SATURATION)


def recency(decided_date: str | None, *, as_of: date | None = None) -> float:
    """Score recency: 1.0 at the decision year, decaying linearly to 0 over 40 years.

    ``as_of`` is injectable for deterministic tests; it defaults to today.
    Unknown dates are neutral (0.5).
    """
    year = parse_year(decided_date)
    if year is None:
        return 0.5
    now = as_of or datetime.now(timezone.utc).date()
    age = now.year - year
    if age <= 0:
        return 1.0
    return max(0.0, 1.0 - age / _RECENCY_WINDOW_YEARS)


def fit(case: dict[str, Any], issue: str) -> float:
    """Score topical fit: keyword overlap between the case and the issue.

    The fraction of issue terms found in the case's title/subject/topic text.
    An empty issue is neutral (0.5).
    """
    issue_terms = _terms(issue)
    if not issue_terms:
        return 0.5
    case_terms = _terms(_case_text(case))
    overlap = len(issue_terms & case_terms) / len(issue_terms)
    return min(1.0, overlap)


def treatment(reconciliation_output: Any) -> float:
    """Score citator treatment from a reconciliation output (state string).

    Accepts a dict (``{"state": ...}``) or an object with a ``.state``
    attribute.  Missing / unknown states are neutral (0.5).
    """
    state = _state_of(reconciliation_output)
    return _TREATMENT_SCORES.get(state, 0.5)


# ---------------------------------------------------------------------------
# combined model
# ---------------------------------------------------------------------------


def persuasive_authority(
    case: dict[str, Any], context: dict[str, Any] | None = None
) -> float:
    """Combine the five factors into a bounded 0..1 persuasive-authority score.

    ``case`` is a legal case node dict (``metadata`` holds the domain data).
    ``context`` may override ``court``, ``target_jurisdiction``, ``issue`` and
    provide a ``reconciliation`` result for the treatment factor.
    """
    ctx = context or {}
    meta = case.get("metadata", {}) if isinstance(case, dict) else {}

    court = ctx.get("court") or meta.get("court", "")
    target_jurisdiction = ctx.get("target_jurisdiction", "federal")
    decided_date = meta.get("decided_date")
    issue = ctx.get("issue", "")
    reconciliation = ctx.get("reconciliation")

    score = (
        WEIGHTS["hierarchy"] * hierarchy(court, target_jurisdiction)
        + WEIGHTS["density"] * density(case)
        + WEIGHTS["recency"] * recency(decided_date)
        + WEIGHTS["fit"] * fit(case, issue)
        + WEIGHTS["treatment"] * treatment(reconciliation)
    )
    return min(1.0, max(0.0, score))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _court_level(court: str) -> float:
    c = (court or "").lower()
    if "scotus" in c:
        return 1.0
    if "supreme" in c and ("united states" in c or "u.s." in c):
        return 1.0
    if "circuit" in c:
        return 0.8
    if "supreme" in c:
        return 0.75
    if "appeal" in c:
        return 0.7
    if "district" in c:
        return 0.6
    return 0.5


def _same_jurisdiction(court: str, target_jurisdiction: str) -> bool:
    if not target_jurisdiction:
        return False
    target = target_jurisdiction.lower()
    c = (court or "").lower()
    if target == "federal":
        return any(
            keyword in c
            for keyword in ("united states", "circuit", "district", "scotus", "u.s.")
        )
    return target in c


def _case_text(case: dict[str, Any]) -> str:
    meta = case.get("metadata", {}) if isinstance(case, dict) else {}
    pieces = [
        case.get("title", ""),
        meta.get("title", ""),
        meta.get("subject", ""),
        meta.get("topic", ""),
        meta.get("keywords", ""),
    ]
    return " ".join(str(piece) for piece in pieces)


def _terms(text: str) -> set[str]:
    normalised = "".join(ch if ch.isalnum() else " " for ch in str(text).lower())
    return {word for word in normalised.split() if word and word not in _STOPWORDS}


def _state_of(reconciliation_output: Any) -> str | None:
    if reconciliation_output is None:
        return None
    if isinstance(reconciliation_output, dict):
        return reconciliation_output.get("state")
    return getattr(reconciliation_output, "state", None)
