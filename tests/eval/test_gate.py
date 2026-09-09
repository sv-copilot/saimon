"""Tests for the offline eval gate (SAIMON-EVAL-CI-GATE-1, #27).

The gate runs every committed fixture suite offline and passes only when each
suite's task success rate meets the threshold. It is the merge/promote signal
wired into CI.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval_harness.gate import gate_suites


def _write_suite(root: Path, name: str, fixtures: list[dict]) -> None:
    suite_dir = root / name
    suite_dir.mkdir(parents=True, exist_ok=True)
    (suite_dir / "fixtures.json").write_text(json.dumps({"fixtures": fixtures}))


def test_gate_passes_when_all_suites_meet_threshold(tmp_path: Path) -> None:
    _write_suite(
        tmp_path,
        "generation",
        [
            {
                "id": "gen-1",
                "input": "x",
                "expected": "ship the eval harness this week",
                "candidate": "ship the eval harness this week",
            }
        ],
    )
    passed, results = gate_suites(str(tmp_path), threshold=0.5)
    assert passed is True
    assert results[0]["suite"] == "generation"
    assert results[0]["passed"] is True


def test_gate_fails_when_a_suite_drops_below_threshold(tmp_path: Path) -> None:
    _write_suite(
        tmp_path,
        "generation",
        [
            {
                "id": "gen-1",
                "input": "x",
                "expected": "ship the eval harness this week",
                "candidate": "ship the eval harness this week",
            }
        ],
    )
    _write_suite(
        tmp_path,
        "verification",
        [
            {
                "id": "verify-1",
                "input": "x",
                "expected": "claim is supported",
                "candidate": "",
            }
        ],
    )
    passed, results = gate_suites(str(tmp_path), threshold=0.5)
    assert passed is False
    by_suite = {r["suite"]: r for r in results}
    assert by_suite["generation"]["passed"] is True
    assert by_suite["verification"]["passed"] is False
    assert by_suite["verification"]["success_rate"] == 0.0


def test_gate_handles_no_suites(tmp_path: Path) -> None:
    passed, results = gate_suites(str(tmp_path), threshold=0.5)
    assert passed is True
    assert results == []
