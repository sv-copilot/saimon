"""Typed relations between claims (#253).

Saimon has only structural edges (`part_of`, `derived_from`), so a claim cannot
corroborate or contradict another and a contradiction is invisible.

The old project's rule, ported: compare numbers and dates first, and only fall
back to semantic similarity when structure cannot decide.

    delta = |a - b| / max(|a|, |b|, 1e-9)
    delta <= 0.10  -> supports     (strength 1 - delta)
    delta >= 0.25  -> contradicts  (strength delta)
    between        -> undecided    (falls back to `related`)

Two guardrails matter more than the arithmetic:

* **Units must match, or the comparison is meaningless.** 5% and 5 people are
  not agreeing.
* **Missing structure is not agreement.** A claim with no number or no date is
  never labelled `supports`; it can only be `related`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

RELATION_VERSION = "v1"

SUPPORT_DELTA = 0.10
CONTRADICT_DELTA = 0.25

# Two percentages are not comparable just because both are percentages: "5% of
# respondents" and "80% accuracy" share a unit and nothing else. Numeric
# agreement or conflict is only claimed when the two claims are already saying
# the same thing in different words.
NUMERIC_SUBJECT_SIMILARITY = 0.90

# Even with the same subject, two claims can share a template and talk about
# different things ("42% of Information-sector businesses" vs "42% of Retail
# Trade businesses" — sampled live and both were labelled contradictory).
# A numeric relation is only claimed when removing the digits leaves the same
# sentence: then the number is the only thing that differs.
SAME_CLAIM_TEXT_RATIO = 0.90


def normalise_without_digits(text: str) -> str:
    lowered = (text or "").lower()
    lowered = re.sub(r"[0-9]", "", lowered)
    lowered = re.sub(r"[^a-z\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def same_claim_text(a: str, b: str) -> bool:
    """True when the two claims differ only in their numbers."""
    left, right = normalise_without_digits(a), normalise_without_digits(b)
    if not left or not right:
        return False
    return SequenceMatcher(None, left, right).ratio() >= SAME_CLAIM_TEXT_RATIO


@dataclass(frozen=True)
class Decision:
    relation: str | None  # 'supports' | 'contradicts' | None (undecided)
    strength: float
    reason: str


def numeric_delta(a: float, b: float) -> float:
    """Relative difference, safe when both values are zero."""
    return abs(a - b) / max(abs(a), abs(b), 1e-9)


def dates_overlap(
    a_start, a_end, b_start, b_end
) -> bool | None:
    """True/False when both spans exist; None when either is unknown."""
    if None in (a_start, a_end, b_start, b_end):
        return None
    return not (a_end < b_start or b_end < a_start)


def compare(
    *,
    a_text: str | None = None,
    b_text: str | None = None,
    similarity: float | None = None,
    a_value: float | None,
    a_unit: str | None,
    a_start=None,
    a_end=None,
    b_value: float | None,
    b_unit: str | None,
    b_start=None,
    b_end=None,
) -> Decision:
    """Decide the relation between two claims from their structured facts."""
    if a_text is not None and b_text is not None and not same_claim_text(a_text, b_text):
        return Decision(None, 0.0, "claims_not_structurally_identical")

    if similarity is not None and similarity < NUMERIC_SUBJECT_SIMILARITY:
        # Structurally comparable, topically unrelated.
        return Decision(None, 0.0, "subjects_not_similar_enough")

    if a_value is None or b_value is None:
        return Decision(None, 0.0, "missing_numeric_value")

    if (a_unit or "") != (b_unit or ""):
        return Decision(None, 0.0, "unit_mismatch")

    overlap = dates_overlap(a_start, a_end, b_start, b_end)
    if overlap is False:
        # A numeric agreement across disjoint periods is not corroboration.
        return Decision(None, 0.0, "date_spans_do_not_overlap")

    delta = numeric_delta(a_value, b_value)
    if delta <= SUPPORT_DELTA:
        return Decision("supports", round(1.0 - delta, 4), f"values_within_{int(SUPPORT_DELTA * 100)}pct")
    if delta >= CONTRADICT_DELTA:
        return Decision("contradicts", round(min(delta, 1.0), 4), "values_diverge")
    return Decision(None, 0.0, "difference_in_undecided_band")
