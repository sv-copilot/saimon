"""Run a committed fixture suite offline and produce a JSON report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import fixtures as fixtures_mod
from . import metrics

DEFAULT_CONFIG = {
    "provider": "fixture",
    "candidate_key": "candidate",
    "success_threshold": 0.5,
}


def run_suite(fixtures_root: str, suite_name: str, config: dict | None = None) -> dict:
    """Execute a fixture suite offline and return a report dict.

    Each fixture is scored against its golden ``expected`` output using the
    candidate selected by ``candidate_key`` (default ``"candidate"``). The
    report carries ``task_success``, ``quality``, ``cost`` and ``latency_ms``
    per fixture plus a summary.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    candidate_key = cfg.get("candidate_key", "candidate")
    threshold = float(cfg.get("success_threshold", 0.5))

    rows: list[dict] = []
    for fixture in fixtures_mod.load_fixtures(fixtures_root, suite_name):
        expected = fixture.get("expected", "")
        candidate = fixture.get(candidate_key, fixture.get("expected", ""))
        rows.append(
            {
                "id": fixture.get("id"),
                "task_success": metrics.is_success(candidate, expected, threshold),
                "quality": metrics.score_quality(candidate, expected),
                "cost": metrics.estimate_cost(
                    candidate, expected, fixture.get("token_usage")
                ),
                "latency_ms": metrics.measure_latency(fixture.get("latency_ms")),
            }
        )

    count = len(rows)
    successes = sum(1 for row in rows if row["task_success"])
    qualities = [row["quality"] for row in rows]
    return {
        "suite": suite_name,
        "config": cfg,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixtures": rows,
        "summary": {
            "fixtures_run": count,
            "task_success_rate": round(successes / count, 4) if count else 0.0,
            "mean_quality": round(sum(qualities) / count, 4) if count else 0.0,
            "total_cost": sum(row["cost"] for row in rows),
            "mean_latency_ms": (
                round(sum(row["latency_ms"] for row in rows) / count, 4)
                if count
                else 0.0
            ),
        },
    }


def write_report(report: dict, output_path: str | Path) -> Path:
    """Serialize a report to disk as JSON (literal Unicode, trailing newline)."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return path
