"""Weighted rubrics for the golden quality corpus (SAIMON-GOLDEN-EVAL-BASELINE-1).

A rubric is a named set of weighted dimensions and a pass threshold. It scores a
report's measured dimensions, never the prose: a dimension is a number in [0, 1]
produced by an explicit measurement in ``scripts/eval_golden.py``.

Missing dimensions are *not* silently zero. A rubric with any dimension the run
did not measure returns ``INCOMPLETE`` — the same fail-closed rule the retrieval
gate uses, because an unmeasured quality number is indistinguishable from a bad
one once it is in a report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCOMPLETE = "INCOMPLETE"

DIMENSION_FLOOR = 0.5


@dataclass(frozen=True)
class Rubric:
    name: str
    weights: dict[str, float]
    pass_threshold: float = 0.75


def load_rubrics(suite_path: str | Path) -> dict[str, Rubric]:
    """Load ``{"rubrics": {name: {pass_threshold, dimensions}}}`` from a suite file."""
    data = json.loads(Path(suite_path).read_text())
    raw = data.get("rubrics") or {}
    rubrics: dict[str, Rubric] = {}
    for name, body in raw.items():
        weights = {k: float(v) for k, v in (body.get("dimensions") or {}).items()}
        if not weights:
            raise ValueError(f"rubric {name} declares no dimensions")
        if any(w < 0 for w in weights.values()):
            raise ValueError(f"rubric {name} has a negative weight")
        rubrics[name] = Rubric(
            name=name,
            weights=weights,
            pass_threshold=float(body.get("pass_threshold", 0.75)),
        )
    return rubrics


def score_rubric(rubric: Rubric, dimensions: dict[str, float | None]) -> dict[str, Any]:
    """Score one rubric. Returns score, verdict, missing and failed dimensions."""
    missing = [name for name in rubric.weights if dimensions.get(name) is None]
    if missing:
        return {
            "rubric": rubric.name,
            "score": None,
            "verdict": VERDICT_INCOMPLETE,
            "missing_dimensions": sorted(missing),
            "failed_dimensions": [],
            "threshold": rubric.pass_threshold,
        }

    total_weight = sum(rubric.weights.values()) or 1.0
    values = {name: float(dimensions[name]) for name in rubric.weights}  # type: ignore[arg-type]
    score = sum(rubric.weights[name] * values[name] for name in rubric.weights) / total_weight
    failed = sorted(name for name in rubric.weights if values[name] < DIMENSION_FLOOR)
    verdict = VERDICT_PASS if score >= rubric.pass_threshold else VERDICT_FAIL
    if failed and verdict == VERDICT_PASS:
        # A weighted average can hide a dead dimension; a dimension under the
        # floor is a failure even when the total clears the threshold.
        verdict = VERDICT_FAIL
    return {
        "rubric": rubric.name,
        "score": round(score, 4),
        "verdict": verdict,
        "missing_dimensions": [],
        "failed_dimensions": failed,
        "threshold": rubric.pass_threshold,
    }


def score_report(report: dict[str, Any], rubrics: dict[str, Rubric]) -> dict[str, Any]:
    """Score every dimension block in a report. Keys of ``report['dimensions']`` are rubric names."""
    dimensions_by_rubric = report.get("dimensions") or {}
    results = {
        name: score_rubric(rubric, dimensions_by_rubric.get(name) or {})
        for name, rubric in rubrics.items()
    }
    verdicts = [r["verdict"] for r in results.values()]
    overall = (
        VERDICT_INCOMPLETE
        if VERDICT_INCOMPLETE in verdicts
        else (VERDICT_FAIL if VERDICT_FAIL in verdicts else VERDICT_PASS)
    )
    return {"overall_verdict": overall, "rubrics": results}


def compare_to_baseline(
    baseline: dict[str, Any], candidate: dict[str, Any], tolerance: float = 0.05
) -> dict[str, Any]:
    """Declare a regression when a dimension drops by more than ``tolerance``.

    A dimension present in the baseline but absent from the candidate is a
    regression: an instrument that stops measuring cannot be called unchanged.
    """
    base = (baseline.get("dimensions") or {})
    cand = (candidate.get("dimensions") or {})
    regressions: list[dict[str, Any]] = []
    for rubric_name, dims in base.items():
        for dim_name, base_value in dims.items():
            cand_value = (cand.get(rubric_name) or {}).get(dim_name)
            if cand_value is None:
                regressions.append(
                    {"rubric": rubric_name, "dimension": dim_name,
                     "baseline": base_value, "candidate": None,
                     "reason": "dimension no longer measured"}
                )
                continue
            if base_value is not None and float(cand_value) < float(base_value) - tolerance:
                regressions.append(
                    {"rubric": rubric_name, "dimension": dim_name,
                     "baseline": base_value, "candidate": cand_value,
                     "reason": f"dropped more than {tolerance}"}
                )
    return {"verdict": "REGRESSION" if regressions else "OK", "regressions": regressions}
