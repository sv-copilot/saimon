"""Golden corpus rubrics + baseline (SAIMON-GOLDEN-EVAL-BASELINE-1).

The baseline is the instrument the rest of EPIC-EPISTEMIC-LAYER-1 is judged with,
so the rules that matter are: an unmeasured dimension cannot pass, a dead
dimension cannot hide behind a weighted average, and a dimension that stops being
measured counts as a regression.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.rubrics import (
    VERDICT_FAIL,
    VERDICT_INCOMPLETE,
    VERDICT_PASS,
    Rubric,
    compare_to_baseline,
    load_rubrics,
    score_report,
    score_rubric,
)

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "fixtures" / "golden" / "suite.json"
BASELINE = ROOT / "reports" / "golden-baseline.json"


class TestRubricLoading:
    def test_suite_declares_all_four_rubrics(self):
        rubrics = load_rubrics(SUITE)
        assert set(rubrics) == {
            "retrieval-rubric-v1",
            "claim-rubric-v1",
            "verification-rubric-v1",
            "degraded-rubric-v1",
        }

    def test_weights_are_positive_and_threshold_set(self):
        for rubric in load_rubrics(SUITE).values():
            assert rubric.pass_threshold == pytest.approx(0.75)
            assert all(w > 0 for w in rubric.weights.values())


class TestScoring:
    def test_all_dimensions_high_passes(self):
        r = Rubric("r", {"a": 0.5, "b": 0.5}, 0.75)
        out = score_rubric(r, {"a": 1.0, "b": 0.9})
        assert out["verdict"] == VERDICT_PASS
        assert out["score"] == pytest.approx(0.95)

    def test_missing_dimension_is_incomplete_not_zero(self):
        r = Rubric("r", {"a": 0.5, "b": 0.5}, 0.75)
        out = score_rubric(r, {"a": 1.0})
        assert out["verdict"] == VERDICT_INCOMPLETE
        assert out["missing_dimensions"] == ["b"]
        assert out["score"] is None

    def test_dead_dimension_fails_even_when_average_clears_threshold(self):
        r = Rubric("r", {"a": 0.9, "b": 0.1}, 0.75)
        out = score_rubric(r, {"a": 1.0, "b": 0.0})
        assert out["score"] >= 0.75  # the average alone would pass
        assert out["verdict"] == VERDICT_FAIL
        assert out["failed_dimensions"] == ["b"]

    def test_low_average_fails(self):
        r = Rubric("r", {"a": 0.5, "b": 0.5}, 0.75)
        assert score_rubric(r, {"a": 0.6, "b": 0.6})["verdict"] == VERDICT_FAIL

    def test_report_incomplete_if_any_rubric_incomplete(self):
        rubrics = load_rubrics(SUITE)
        out = score_report({"dimensions": {"claim-rubric-v1": {
            "structural_precision": 0.9, "numeric_signal": 1.0}}}, rubrics)
        assert out["overall_verdict"] == VERDICT_INCOMPLETE


class TestBaselineComparison:
    def test_drop_beyond_tolerance_is_a_regression(self):
        base = {"dimensions": {"r": {"a": 0.9}}}
        cand = {"dimensions": {"r": {"a": 0.80}}}
        assert compare_to_baseline(base, cand, tolerance=0.05)["verdict"] == "REGRESSION"

    def test_small_drop_is_tolerated(self):
        base = {"dimensions": {"r": {"a": 0.90}}}
        cand = {"dimensions": {"r": {"a": 0.87}}}
        assert compare_to_baseline(base, cand, tolerance=0.05)["verdict"] == "OK"

    def test_unmeasured_dimension_is_a_regression(self):
        base = {"dimensions": {"r": {"a": 0.9}}}
        cand = {"dimensions": {"r": {}}}
        result = compare_to_baseline(base, cand)
        assert result["verdict"] == "REGRESSION"
        assert result["regressions"][0]["reason"] == "dimension no longer measured"


class TestCommittedBaseline:
    def test_baseline_exists_and_is_self_consistent(self):
        assert BASELINE.is_file(), "reports/golden-baseline.json must be committed"
        report = json.loads(BASELINE.read_text())
        rescored = score_report(report, load_rubrics(SUITE))
        assert report["scored"]["overall_verdict"] == rescored["overall_verdict"]

    def test_one_doctored_dimension_turns_the_verdict(self):
        report = json.loads(BASELINE.read_text())
        doctored = json.loads(json.dumps(report))
        for dims in doctored["dimensions"].values():
            for key in dims:
                dims[key] = 0.0 if dims[key] is not None else None
        rescored = score_report(doctored, load_rubrics(SUITE))
        assert rescored["overall_verdict"] != VERDICT_PASS
