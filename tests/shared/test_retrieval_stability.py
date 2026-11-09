"""Corpus-perturbation stability (SAIMON-RETRIEVAL-STABILITY-1).

Retrieval scores are relative to the candidate set, so three extra documents
moved `pgvector hnsw tuning` from 0.816 to a sub-threshold score. These tests pin
the comparison logic that makes such a flip visible.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "retrieval_stability.py"
_spec = importlib.util.spec_from_file_location("retrieval_stability", _PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)


class TestVerdicts:
    def test_hit_and_miss_rows(self):
        rows = [
            {"id": "a", "kind": "retrieval", "hit": True},
            {"id": "b", "kind": "retrieval", "hit": False},
        ]
        assert _mod.verdicts(rows) == {"a": "hit", "b": "miss"}

    def test_abstain_and_leak_rows(self):
        rows = [
            {"id": "x", "kind": "abstain", "ok": True},
            {"id": "y", "kind": "abstain", "ok": False},
        ]
        assert _mod.verdicts(rows) == {"x": "abstain", "y": "leak"}


class TestCompare:
    def test_no_change_is_stable(self):
        same = {"a": "hit", "b": "abstain"}
        assert _mod.compare_verdicts(same, dict(same)) == []

    def test_hit_to_miss_is_a_flip(self):
        flips = _mod.compare_verdicts({"a": "hit"}, {"a": "miss"})
        assert flips == [{"id": "a", "before": "hit", "after": "miss"}]

    def test_abstain_to_leak_is_a_flip(self):
        flips = _mod.compare_verdicts({"a": "abstain"}, {"a": "leak"})
        assert flips[0]["after"] == "leak"

    def test_new_and_missing_cases_are_flips(self):
        assert _mod.compare_verdicts({}, {"a": "hit"})
        assert _mod.compare_verdicts({"a": "hit"}, {})
