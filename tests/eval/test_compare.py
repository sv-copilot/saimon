"""Tests for the offline eval harness report comparison."""

from __future__ import annotations

from eval_harness.compare import compare_reports


def _report(quality: float, task_success: bool = True) -> dict:
    return {
        "suite": "generation",
        "fixtures": [
            {
                "id": "gen-1",
                "task_success": task_success,
                "quality": quality,
                "cost": 10,
                "latency_ms": 50.0,
            }
        ],
    }


def test_compare_detects_quality_regression() -> None:
    result = compare_reports(_report(0.95), _report(0.70), quality_threshold=0.05)
    assert result["verdict"] == "REGRESSION"
    assert "gen-1" in result["regressions"]


def test_compare_exits_ok_within_threshold() -> None:
    result = compare_reports(_report(0.95), _report(0.93), quality_threshold=0.05)
    assert result["verdict"] == "OK"
    assert result["regressions"] == []


def test_compare_detects_task_success_drop() -> None:
    result = compare_reports(
        _report(0.95, task_success=True), _report(0.95, task_success=False)
    )
    assert result["verdict"] == "REGRESSION"
    assert "gen-1" in result["regressions"]
