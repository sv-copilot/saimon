"""Bounded quality and primacy priors in retrieval (#273).

Ranks come from relevance; these priors only break ties and demote weak evidence.
Two numbers decide the adjustment:

* **quality** — how much to trust the row (0-1, higher is better).
* **primacy** — distance from primary evidence (0-1, lower is closer).

The adjustment is multiplicative and capped, because an unbounded prior turns a
ranking into a popularity contest: a well-cited paper would outrank better
evidence forever. The cap is what keeps "a well-supported dissent is never
buried" true — a strong contradiction still carries its relevance.

When either input is missing the prior contributes nothing: a default is not a
measurement, and inventing 0.5 for an unscored row would quietly reward the
unscored.
"""

from __future__ import annotations

QUALITY_WEIGHT = 0.10
PRIMACY_WEIGHT = 0.08
# The cap equals the largest swing the weights can produce (0.10*0.5 + 0.08*0.5),
# so it is a real bound rather than a number the maths can never reach.
MAX_BONUS = QUALITY_WEIGHT * 0.5 + PRIMACY_WEIGHT * 0.5


def _bound(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def prior_contribution(
    *, quality: float | None, primacy: float | None
) -> tuple[float, dict]:
    """Return (multiplicative bonus, explanation). Zero when inputs are absent."""
    parts: dict[str, float | None] = {"quality": quality, "primacy": primacy}
    if quality is None and primacy is None:
        return 0.0, {**parts, "bonus": 0.0, "reason": "no_prior_inputs"}

    bonus = 0.0
    if quality is not None:
        bonus += QUALITY_WEIGHT * (_bound(quality) - 0.5)
    if primacy is not None:
        # Lower distance is better, so a near-primary row gains and a far row loses.
        bonus += PRIMACY_WEIGHT * (0.5 - _bound(primacy))

    capped = max(-MAX_BONUS, min(bonus, MAX_BONUS))
    return capped, {
        **parts,
        "bonus": round(capped, 4),
        "capped": abs(bonus) >= MAX_BONUS - 1e-9,
    }


def adjust_score(
    score: float, *, quality: float | None, primacy: float | None
) -> tuple[float, dict]:
    """Apply the bounded prior to one relevance score."""
    bonus, detail = prior_contribution(quality=quality, primacy=primacy)
    return round(score * (1.0 + bonus), 6), detail


def apply_priors(rows: list[dict]) -> list[dict]:
    """Re-score and re-order rows that carry ``quality_score``/``primacy_distance_score``."""
    adjusted = []
    for row in rows:
        score = float(row.get("relevance_score") or 0.0)
        new_score, detail = adjust_score(
            score,
            quality=row.get("quality_score"),
            primacy=row.get("primacy_distance_score"),
        )
        adjusted.append({
            **row,
            "relevance_score_before_prior": round(score, 6),
            "relevance_score": new_score,
            "prior": detail,
        })
    adjusted.sort(key=lambda r: r["relevance_score"], reverse=True)
    return adjusted
