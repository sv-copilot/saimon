"""Retrieval policy snapshots and drift detection (SAIMON-RETRIEVAL-DRIFT-CHECK-1).

Quality measured once is an anecdote. This records each golden run's dimensions
alongside the corpus shape and the code revision, so a later run can be compared
to it and a regression can fail a check instead of surfacing as a bad answer
weeks later.

Snapshots are append-only files: a run never rewrites history.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval_harness.rubrics import compare_to_baseline

SNAPSHOT_DIR = "reports/snapshots"


def build_snapshot(
    report: dict[str, Any],
    *,
    corpus_counts: dict[str, int] | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    """Reduce a golden report to a comparable snapshot."""
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "revision": revision,
        "dimensions": report.get("dimensions") or {},
        "scored": report.get("scored") or {},
        "corpus": corpus_counts or {},
    }


def write_snapshot(snapshot: dict[str, Any], directory: str | Path = SNAPSHOT_DIR) -> Path:
    """Append a snapshot under the directory, named by timestamp."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = target / f"golden-{stamp}.json"
    suffix = 1
    while path.exists():  # never overwrite
        path = target / f"golden-{stamp}-{suffix}.json"
        suffix += 1
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    return path


def load_snapshots(directory: str | Path = SNAPSHOT_DIR) -> list[dict[str, Any]]:
    target = Path(directory)
    if not target.is_dir():
        return []
    snapshots = []
    # Sort by mtime: two snapshots in the same second share a timestamp stem, so
    # filename order is not insertion order.
    for path in sorted(target.glob("golden-*.json"), key=lambda item: item.stat().st_mtime):
        try:
            snapshots.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return snapshots


def check_drift(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    tolerance: float = 0.05,
) -> dict[str, Any]:
    """Compare two snapshots; a dropped dimension is a drift."""
    result = compare_to_baseline(baseline, current, tolerance=tolerance)
    return {
        "verdict": result["verdict"],
        "regressions": result["regressions"],
        "corpus_delta": _corpus_delta(baseline.get("corpus") or {}, current.get("corpus") or {}),
    }


def _corpus_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        key: int(after.get(key, 0)) - int(before.get(key, 0))
        for key in sorted(set(before) | set(after))
        if int(after.get(key, 0)) != int(before.get(key, 0))
    }


def trend(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-snapshot summary, oldest first, for a quick read of movement."""
    rows = []
    for snap in snapshots:
        dims = snap.get("dimensions") or {}
        flat = {f"{rubric}.{dim}": value for rubric, dims_ in dims.items() for dim, value in dims_.items()}
        rows.append(
            {
                "generated_at": snap.get("generated_at"),
                "revision": snap.get("revision"),
                "overall": (snap.get("scored") or {}).get("overall_verdict"),
                "metrics": flat,
            }
        )
    return rows
