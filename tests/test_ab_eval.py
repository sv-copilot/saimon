"""Tests for the four-arm release A/B harness.

The metrics are the contract: a release is graded on them, so each one is pinned here -
including the case the gate exists to catch (a release that improves its success rate by
fabricating answers to questions the corpus cannot answer).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval_harness import ab

TASK_ANSWERABLE = {"id": "t1", "kind": "answerable", "query": "q", "must_include": ["429"]}
TASK_UNANSWERABLE = {"id": "t2", "kind": "unanswerable", "query": "capital of Mongolia", "must_include": []}


class TestScoring:
    def test_answerable_needs_every_required_fact(self):
        assert ab.score_answer("The code is 429.", TASK_ANSWERABLE)["success"] is True
        assert ab.score_answer("The code is 404.", TASK_ANSWERABLE)["success"] is False

    def test_answerable_refusal_is_a_failure(self):
        graded = ab.score_answer("I do not know.", TASK_ANSWERABLE)
        assert graded["success"] is False
        assert graded["abstained"] is True

    def test_unanswerable_success_is_a_refusal(self):
        assert ab.score_answer("I do not know.", TASK_UNANSWERABLE)["success"] is True

    def test_unanswerable_confident_answer_is_a_failure(self):
        assert ab.score_answer("The capital is Ulaanbaatar.", TASK_UNANSWERABLE)["success"] is False

    def test_refusal_variants_are_recognised(self):
        for text in ("Not in the context.", "The context does not contain this.", "No strong evidence."):
            assert ab.is_refusal(text) is True, text

    def test_groundedness_counts_required_facts_in_context(self):
        task = {"must_include": ["environment", "behavior"]}
        assert ab.groundedness("the environment shapes behavior", task) == 1.0
        assert ab.groundedness("the environment", task) == 0.5
        assert ab.groundedness("unrelated", task) == 0.0
        assert ab.groundedness("anything", {"must_include": []}) is None


class TestBootstrap:
    def _rows(self, successes):
        return [{"task_id": f"t{i}", "success": s} for i, s in enumerate(successes)]

    def test_identical_arms_have_zero_difference(self):
        rows = self._rows([True, False, True])
        result = ab.paired_bootstrap(rows, rows)
        assert result["mean_diff"] == 0.0
        assert result["ci95"] == [0.0, 0.0]

    def test_every_task_improved_puts_the_interval_above_zero(self):
        before = self._rows([False, False, False, False])
        after = self._rows([True, True, True, True])
        result = ab.paired_bootstrap(before, after)
        assert result["mean_diff"] == 1.0
        assert result["ci95"][0] > 0

    def test_mixed_change_reports_both_directions(self):
        before = self._rows([True, True, False, False])
        after = self._rows([True, False, True, True])
        result = ab.paired_bootstrap(before, after)
        assert result["improved"] == 2 and result["regressed"] == 1
        assert result["mean_diff"] == 0.25




TARGETS = {
        "thresholds": {
            "current_vs_baseline_success_gain": 0.15,
            "current_vs_previous_success_drop_max": 0.02,
            "current_abstain_accuracy_min": 1.0,
            "current_p95_latency_ratio_max": 1.5,
            "current_cost_ratio_vs_previous_max": 1.2,
            "current_groundedness_min": 0.75,
        }
    }


class TestGate:
    def _report(self, current, previous=None, baseline=None):
        arms = [
            {"id": "current", "skipped": None, "summary": current},
        ]
        if previous:
            arms.append({"id": "previous", "skipped": None, "summary": previous})
        if baseline:
            arms.append({"id": "baseline", "skipped": None, "summary": baseline})
        return {"arms": arms}

    def summary(self, **over):
        base = {
            "success_rate": 0.83,
            "abstain_accuracy": 1.0,
            "groundedness_mean": 0.9,
            "latency_p95_ms": 100.0,
            "cost_mean_usd": 0.001,
        }
        base.update(over)
        return base

    def test_a_clean_release_passes(self):
        verdict = ab.evaluate_gate(
            self._report(self.summary(), self.summary(), self.summary(success_rate=0.5)),
            TARGETS,
        )
        assert verdict["verdict"] == "PASS"

    def test_fabrication_fails_even_with_a_higher_success_rate(self):
        report = self._report(self.summary(success_rate=1.0, abstain_accuracy=0.5), self.summary(), self.summary())
        verdict = ab.evaluate_gate(report, TARGETS)
        assert verdict["verdict"] == "FAIL"
        failed = {c["check"] for c in verdict["checks"] if c["status"] == "fail"}
        assert "current_abstain_accuracy" in failed

    def test_regression_against_previous_release_fails(self):
        report = self._report(self.summary(success_rate=0.7), self.summary(success_rate=0.9), self.summary())
        verdict = ab.evaluate_gate(report, TARGETS)
        failed = {c["check"] for c in verdict["checks"] if c["status"] == "fail"}
        assert "current_vs_previous_success_drop" in failed

    def test_missing_previous_release_is_skipped_not_passed(self):
        verdict = ab.evaluate_gate(self._report(self.summary()), TARGETS)
        statuses = {c["check"]: c["status"] for c in verdict["checks"]}
        assert statuses["current_vs_previous_success_drop"] == "skipped"
        assert verdict["verdict"] in {"PASS", "UNMEASURED"}


class TestEndToEndFake:
    def test_all_four_arms_run_and_the_gate_passes(self, tmp_path):
        out = tmp_path / "report.json"
        done = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "ab_eval.py"), "run",
                "--provider", "fake",
                "--rag-url", "http://rag", "--previous-url", "http://prev", "--current-url", "http://cur",
                "--out", str(out),
            ],
            capture_output=True, text=True, cwd=ROOT, check=False,
        )
        assert done.returncode == 0, done.stderr
        report = json.loads(out.read_text())

        assert [a["id"] for a in report["arms"]] == ["baseline", "rag", "previous", "current"]
        assert all(not a.get("skipped") for a in report["arms"])

        by_id = {a["id"]: a["summary"] for a in report["arms"]}
        # The ungated arm answers the unanswerable tasks; the gated releases refuse them.
        assert by_id["rag"]["abstain_accuracy"] == 0.0
        assert by_id["previous"]["abstain_accuracy"] == 1.0
        assert by_id["current"]["abstain_accuracy"] == 1.0
        assert report["gate"]["verdict"] == "PASS"

    def test_gate_command_exits_zero_on_pass(self, tmp_path):
        out = tmp_path / "report.json"
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ab_eval.py"), "run", "--provider", "fake",
             "--rag-url", "http://rag", "--previous-url", "http://prev", "--current-url", "http://cur",
             "--out", str(out)],
            capture_output=True, text=True, cwd=ROOT, check=True,
        )
        gate = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ab_eval.py"), "gate", "--report", str(out)],
            capture_output=True, text=True, cwd=ROOT, check=False,
        )
        assert gate.returncode == 0, gate.stdout + gate.stderr
