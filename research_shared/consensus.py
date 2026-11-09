"""Contradiction and consensus views over claim relations (#274).

"What does the corpus agree on, where does it conflict, and where is it silent"
is the question the whole epistemic layer exists to answer. It is also the view
where a bug is most damaging: an averaged contradiction reads as agreement.

Three rules:

* **Contested is never averaged.** A claim with both supporting and dissenting
  relations is reported as contested, with both sides listed.
* **Silence is stated.** No relations is a finding, not an empty list.
* **Every member carries provenance** — the edge id and the reason for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONSENSUS = "consensus"
CONTESTED = "contested"
CONTRADICTION = "contradiction"
SILENT = "silent"


@dataclass
class Cluster:
    label: str
    claims: list[dict] = field(default_factory=list)
    note: str | None = None


@dataclass
class ConsensusView:
    seed_id: str | None
    outcome: str
    supporting: list[dict] = field(default_factory=list)
    dissenting: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "seed_id": self.seed_id,
            "outcome": self.outcome,
            "supporting": self.supporting,
            "dissenting": self.dissenting,
            "unresolved": self.unresolved,
            "counts": {
                "supporting": len(self.supporting),
                "dissenting": len(self.dissenting),
                "unresolved": len(self.unresolved),
            },
        }


def _member(row: dict) -> dict:
    return {
        "id": str(row.get("id") or row.get("target_id") or ""),
        "title": row.get("title"),
        "relation": row.get("relation_type"),
        "strength": row.get("weight"),
        "reason": (row.get("metadata") or {}).get("reason")
        if isinstance(row.get("metadata"), dict)
        else None,
    }


def build_view(seed_id: str | None, relations: list[dict]) -> ConsensusView:
    """Turn a seed's relations into a view. ``relations`` may be empty."""
    if not relations:
        return ConsensusView(seed_id=seed_id, outcome=SILENT)

    supporting, dissenting, unresolved = [], [], []
    for row in relations:
        relation = (row.get("relation_type") or "").lower()
        if relation == "supports":
            supporting.append(_member(row))
        elif relation in ("contradicts", "dissents"):
            dissenting.append(_member(row))
        else:
            unresolved.append(_member(row))

    if supporting and dissenting:
        outcome = CONTESTED
    elif dissenting:
        outcome = CONTRADICTION
    elif supporting:
        outcome = CONSENSUS
    else:
        outcome = SILENT

    return ConsensusView(
        seed_id=seed_id,
        outcome=outcome,
        supporting=supporting,
        dissenting=dissenting,
        unresolved=unresolved,
    )


def summarise(views: list[ConsensusView]) -> dict:
    """Aggregate many views into one report for a topic."""
    counts = {CONSENSUS: 0, CONTESTED: 0, CONTRADICTION: 0, SILENT: 0}
    contested = []
    for view in views:
        counts[view.outcome] = counts.get(view.outcome, 0) + 1
        if view.outcome == CONTESTED:
            contested.append(view)
    return {
        "claims_examined": len(views),
        "outcomes": counts,
        "contested": [v.as_dict() for v in contested],
        "silent_claims": [v.seed_id for v in views if v.outcome == SILENT],
    }
