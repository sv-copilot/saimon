"""Tests for the offline eval harness runner."""

from __future__ import annotations

import json
from pathlib import Path

from eval_harness.runner import run_suite, write_report


def _write_suite(root: Path, fixtures: list[dict]) -> Path:
    """Create a generation suite under root and return the suite dir."""
    suite_dir = root / "generation"
    suite_dir.mkdir(parents=True, exist_ok=True)
    (suite_dir / "fixtures.json").write_text(json.dumps({"fixtures": fixtures}))
    return suite_dir


def test_run_emits_required_metric_fields(tmp_path: Path) -> None:
    _write_suite(
        tmp_path,
        [
            {
                "id": "gen-1",
                "input": "Summarize the meeting.",
                "expected": "The team agreed to ship the eval harness this week.",
                "candidate": "The team agreed to ship the eval harness this week.",
            }
        ],
    )
    report = run_suite(
        str(tmp_path),
        "generation",
        {"candidate_key": "candidate", "success_threshold": 0.5},
    )

    assert report["suite"] == "generation"
    assert len(report["fixtures"]) == 1
    fixture_report = report["fixtures"][0]
    assert isinstance(fixture_report["task_success"], bool)
    assert isinstance(fixture_report["quality"], float)
    assert isinstance(fixture_report["cost"], (int, float))
    assert isinstance(fixture_report["latency_ms"], (int, float))
    assert report["summary"]["fixtures_run"] == 1


def test_run_writes_json_report(tmp_path: Path) -> None:
    _write_suite(
        tmp_path,
        [
            {
                "id": "gen-1",
                "input": "Draft a subject line.",
                "expected": "Q3 planning update",
                "candidate": "Quarter three planning update",
                "token_usage": 8,
                "latency_ms": 60.0,
            }
        ],
    )
    report = run_suite(str(tmp_path), "generation")
    out = tmp_path / "report.json"
    write_report(report, out)

    parsed = json.loads(out.read_text())
    assert parsed["suite"] == "generation"
    assert parsed["fixtures"][0]["id"] == "gen-1"
    assert "quality" in parsed["fixtures"][0]
    assert "cost" in parsed["fixtures"][0]
    assert "latency_ms" in parsed["fixtures"][0]


def test_run_works_offline(tmp_path: Path, monkeypatch) -> None:
    # Strip any live model keys — the harness must never need them.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    _write_suite(
        tmp_path,
        [
            {
                "id": "gen-1",
                "input": "Hello",
                "expected": "hello world",
                "candidate": "hello world",
            }
        ],
    )
    report = run_suite(str(tmp_path), "generation")

    assert report["fixtures"][0]["task_success"] is True
    assert report["fixtures"][0]["quality"] == 1.0
