"""Policy snapshots and drift detection (SAIMON-RETRIEVAL-DRIFT-CHECK-1).

A single measurement is an anecdote. These pin the properties that make the
history trustworthy: snapshots never overwrite, a dropped dimension fails the
check, and the corpus delta is reported alongside the metric.
"""

from __future__ import annotations

from pathlib import Path

from research_shared.policy import (
    build_snapshot,
    check_drift,
    load_snapshots,
    trend,
    write_snapshot,
)


def _report(hit_rate: float = 1.0, verdict: str = "PASS") -> dict:
    return {
        "dimensions": {"retrieval-rubric-v1": {"hit_rate": hit_rate, "abstention": 1.0}},
        "scored": {"overall_verdict": verdict},
    }


class TestSnapshots:
    def test_build_records_dimensions_and_revision(self):
        snap = build_snapshot(_report(), corpus_counts={"documents": 49}, revision="abc123")
        assert snap["dimensions"]["retrieval-rubric-v1"]["hit_rate"] == 1.0
        assert snap["corpus"]["documents"] == 49
        assert snap["revision"] == "abc123"

    def test_write_never_overwrites(self, tmp_path: Path):
        snap = build_snapshot(_report())
        first = write_snapshot(snap, tmp_path)
        second = write_snapshot(snap, tmp_path)
        assert first != second
        assert first.exists() and second.exists()

    def test_load_returns_oldest_first(self, tmp_path: Path):
        write_snapshot(build_snapshot(_report(hit_rate=0.9)), tmp_path)
        write_snapshot(build_snapshot(_report(hit_rate=1.0)), tmp_path)
        loaded = load_snapshots(tmp_path)
        assert len(loaded) == 2
        assert loaded[0]["dimensions"]["retrieval-rubric-v1"]["hit_rate"] == 0.9

    def test_missing_directory_is_empty(self, tmp_path: Path):
        assert load_snapshots(tmp_path / "nope") == []


class TestDrift:
    def test_unchanged_is_ok(self):
        assert check_drift(build_snapshot(_report()), build_snapshot(_report()))["verdict"] == "OK"

    def test_drop_beyond_tolerance_is_drift(self):
        before = build_snapshot(_report(hit_rate=1.0))
        after = build_snapshot(_report(hit_rate=0.80))
        result = check_drift(before, after, tolerance=0.05)
        assert result["verdict"] == "REGRESSION"
        assert result["regressions"][0]["dimension"] == "hit_rate"

    def test_corpus_delta_is_reported(self):
        before = build_snapshot(_report(), corpus_counts={"documents": 45})
        after = build_snapshot(_report(), corpus_counts={"documents": 49})
        assert check_drift(before, after)["corpus_delta"] == {"documents": 4}

    def test_tiny_drop_is_within_tolerance(self):
        before = build_snapshot(_report(hit_rate=1.0))
        after = build_snapshot(_report(hit_rate=0.97))
        assert check_drift(before, after, tolerance=0.05)["verdict"] == "OK"


class TestTrend:
    def test_flattens_metrics_per_snapshot(self):
        rows = trend([
            {"generated_at": "t1", "revision": "a", "scored": {"overall_verdict": "PASS"},
             "dimensions": {"retrieval-rubric-v1": {"hit_rate": 1.0}}},
        ])
        assert rows[0]["metrics"]["retrieval-rubric-v1.hit_rate"] == 1.0
