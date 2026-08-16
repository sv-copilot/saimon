"""reconcile.py — the reconciliation engine (slice #70).

Maps heterogeneous citator treatment codes to a canonical
``POSITIVE | NEUTRAL | NEGATIVE``, detects disagreements between source pairs,
builds a brief-citation usage signal from 3/6/12/24-month windows, and
classifies a case into one of six canonical states.

Pure logic — no network I/O.  Citators are inputs, never ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- canonical treatment values -------------------------------------------

POSITIVE = "POSITIVE"
NEUTRAL = "NEUTRAL"
NEGATIVE = "NEGATIVE"

#: Raw citator treatment codes mapped to a canonical treatment.
_TREATMENT_MAP: dict[str, str] = {
    # positive — the case was followed / approved
    "followed": POSITIVE,
    "affirmed": POSITIVE,
    "approved": POSITIVE,
    "upheld": POSITIVE,
    "applied": POSITIVE,
    "cited": POSITIVE,
    "cited favorably": POSITIVE,
    "positive": POSITIVE,
    "green": POSITIVE,
    "good law": POSITIVE,
    "adhered to": POSITIVE,
    "confirmed": POSITIVE,
    # neutral — distinguished / limited, not clearly good or bad
    "distinguished": NEUTRAL,
    "explained": NEUTRAL,
    "harmonized": NEUTRAL,
    "limited": NEUTRAL,
    "modified": NEUTRAL,
    "clarified": NEUTRAL,
    "analyzed": NEUTRAL,
    "questioned": NEUTRAL,
    "cautionary": NEUTRAL,
    "cautioned": NEUTRAL,
    "yellow": NEUTRAL,
    "neutral": NEUTRAL,
    "no treatment": NEUTRAL,
    # negative — the case was overruled / criticized
    "overruled": NEGATIVE,
    "reversed": NEGATIVE,
    "vacated": NEGATIVE,
    "criticized": NEGATIVE,
    "disapproved": NEGATIVE,
    "abrogated": NEGATIVE,
    "superseded": NEGATIVE,
    "negative": NEGATIVE,
    "red": NEGATIVE,
    "bad law": NEGATIVE,
    "not followed": NEGATIVE,
    "declined to follow": NEGATIVE,
    "no longer good law": NEGATIVE,
}

#: The six canonical classification states.
STRONG_GREEN = "STRONG_GREEN"
WEAK_GREEN = "WEAK_GREEN"
YELLOW = "YELLOW"
CITATOR_RED = "CITATOR_RED"
MARKET_RED = "MARKET_RED"
RESURRECTION = "RESURRECTION"

CLASSIFICATION_STATES = frozenset(
    {STRONG_GREEN, WEAK_GREEN, YELLOW, CITATOR_RED, MARKET_RED, RESURRECTION}
)


def canonical_treatment(code: str) -> str:
    """Map a raw citator treatment code to ``POSITIVE|NEUTRAL|NEGATIVE``.

    Normalises case and whitespace, then looks the code up in the treatment
    table.  Unknown codes fall back to ``NEUTRAL`` (never crash on new citator
    data).
    """
    return _TREATMENT_MAP.get(code.strip().lower(), NEUTRAL)


@dataclass(frozen=True)
class Disagreement:
    """A disagreement between two citators over a case's treatment."""

    source_a: str
    source_b: str
    treatment_a: str
    treatment_b: str


def detect_disagreements(entries: list[dict[str, Any]]) -> list[Disagreement]:
    """Return a disagreement for every source pair with differing treatment.

    ``entries`` is a list of ``{"source": str, "treatment": str}`` dicts where
    ``treatment`` may be a raw code or an already-canonical value.  Output is
    deterministic: sources are ordered and each unordered pair is visited once.
    """
    normalized = sorted(
        (
            (entry["source"], canonical_treatment(entry["treatment"]))
            for entry in entries
        ),
        key=lambda item: item[0],
    )
    disagreements: list[Disagreement] = []
    for index, (source_a, treatment_a) in enumerate(normalized):
        for source_b, treatment_b in normalized[index + 1 :]:
            if treatment_a != treatment_b:
                disagreements.append(
                    Disagreement(source_a, source_b, treatment_a, treatment_b)
                )
    return disagreements


def build_usage_signal(citations_by_window: dict[str, int]) -> dict[str, Any]:
    """Build a brief-citation usage signal from cumulative 3/6/12/24-month counts.

    ``citations_by_window`` maps ``"3m"``, ``"6m"``, ``"12m"``, ``"24m"`` to
    cumulative citation counts.  Missing keys default to 0 and the windows are
    clamped to be non-decreasing (a later window can never contain fewer
    citations than an earlier one).

    Returns a dict with the normalised windows plus three mutually exclusive
    flags:

    - ``active`` — citations within the last 3 months.
    - ``declining`` — no citations in the last 3 months but some within 24.
    - ``stale`` — no citations at all in the last 24 months.
    """
    c3 = int(citations_by_window.get("3m", 0))
    c6 = int(citations_by_window.get("6m", 0))
    c12 = int(citations_by_window.get("12m", 0))
    c24 = int(citations_by_window.get("24m", 0))
    # Cumulative windows are monotonic; clamp defensively.
    c6 = max(c6, c3)
    c12 = max(c12, c6)
    c24 = max(c24, c12)

    active = c3 > 0
    stale = c24 == 0
    return {
        "windows": {"3m": c3, "6m": c6, "12m": c12, "24m": c24},
        "active": active,
        "declining": not active and not stale,
        "stale": stale,
    }


@dataclass
class Classification:
    """The outcome of reconciling a case's citator + usage inputs."""

    state: str
    consensus: str
    disagreements: list[Disagreement] = field(default_factory=list)
    usage_signal: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


def classify(
    citator_map: dict[str, str], usage_signal: dict[str, Any]
) -> Classification:
    """Classify a case into one of six states.

    ``citator_map`` maps citator source names to raw treatment codes.
    ``usage_signal`` is the dict produced by :func:`build_usage_signal`.

    Ladder (first match wins):

    1. positive AND negative present → ``YELLOW`` (directional disagreement).
    2. negative present, no positive: active usage → ``RESURRECTION``,
       otherwise ``CITATOR_RED``.
    3. positive present, no negative: stale usage → ``MARKET_RED``;
       active → ``STRONG_GREEN``; otherwise ``WEAK_GREEN``.
    4. otherwise (only neutral, or no entries) → ``YELLOW`` with ``NEUTRAL``
       consensus.
    """
    treatments = {
        source: canonical_treatment(code) for source, code in citator_map.items()
    }
    entries = [
        {"source": source, "treatment": treatment}
        for source, treatment in treatments.items()
    ]
    disagreements = detect_disagreements(entries)

    positives = {s for s, t in treatments.items() if t == POSITIVE}
    negatives = {s for s, t in treatments.items() if t == NEGATIVE}

    if positives and negatives:
        return Classification(
            state=YELLOW,
            consensus="MIXED",
            disagreements=disagreements,
            usage_signal=usage_signal,
            rationale="opposing citator treatments (positive vs negative)",
        )

    if negatives:
        if usage_signal.get("active"):
            return Classification(
                state=RESURRECTION,
                consensus=NEGATIVE,
                disagreements=disagreements,
                usage_signal=usage_signal,
                rationale="negative citators but active brief usage",
            )
        return Classification(
            state=CITATOR_RED,
            consensus=NEGATIVE,
            disagreements=disagreements,
            usage_signal=usage_signal,
            rationale="negative citators without active brief usage",
        )

    if positives:
        if usage_signal.get("stale"):
            return Classification(
                state=MARKET_RED,
                consensus=POSITIVE,
                disagreements=disagreements,
                usage_signal=usage_signal,
                rationale="positive citators but no brief usage in 24 months",
            )
        if usage_signal.get("active"):
            return Classification(
                state=STRONG_GREEN,
                consensus=POSITIVE,
                disagreements=disagreements,
                usage_signal=usage_signal,
                rationale="positive citators and active brief usage",
            )
        return Classification(
            state=WEAK_GREEN,
            consensus=POSITIVE,
            disagreements=disagreements,
            usage_signal=usage_signal,
            rationale="positive citators but declining brief usage",
        )

    return Classification(
        state=YELLOW,
        consensus=NEUTRAL,
        disagreements=disagreements,
        usage_signal=usage_signal,
        rationale="no directional citator signal",
    )
