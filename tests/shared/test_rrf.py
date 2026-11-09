"""Reciprocal-rank fusion (SAIMON-HYBRID-RRF-1).

RRF exists because the two retrieval signals are not comparable on score. It
also fixes a structural gap: the old merge took vector results first and
truncated, so lexical-only hits were lost whenever vectors filled the quota.
"""

from __future__ import annotations

import pytest

from research_shared.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion


class TestFusion:
    def test_identical_lists_keep_their_order(self):
        fused = reciprocal_rank_fusion([["a", "b", "c"], ["a", "b", "c"]])
        assert [doc for doc, _ in fused] == ["a", "b", "c"]

    def test_consistent_second_place_beats_inconsistent_first(self):
        fused = reciprocal_rank_fusion(
            [["only_vector", "steady"], ["only_keyword", "steady"]],
        )
        ids = [doc for doc, _ in fused]
        assert ids[0] == "steady"

    def test_lexical_only_hit_is_kept(self):
        fused = reciprocal_rank_fusion([["v1", "v2"], ["k1"]], limit=3)
        ids = [doc for doc, _ in fused]
        assert "k1" in ids

    def test_limit_truncates_after_ranking(self):
        fused = reciprocal_rank_fusion([["a", "b", "c", "d"]], limit=2)
        assert len(fused) == 2
        assert [doc for doc, _ in fused] == ["a", "b"]

    def test_deterministic_tie_break(self):
        first = reciprocal_rank_fusion([["b"], ["a"]])
        second = reciprocal_rank_fusion([["a"], ["b"]])
        assert [d for d, _ in first] == [d for d, _ in second]

    def test_duplicates_within_a_list_use_the_best_rank(self):
        fused = reciprocal_rank_fusion([["a", "a", "b"]])
        assert dict(fused)["a"] == pytest.approx(1 / (DEFAULT_RRF_K + 1))

    def test_empty_input(self):
        assert reciprocal_rank_fusion([[], []]) == []

    def test_k_must_be_positive(self):
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([["a"]], k=0)


class TestMergeWiring:
    def test_merge_uses_fusion_not_vector_first(self):
        import inspect

        from saimon_mcp.search import server

        src = inspect.getsource(server._merge_results)
        assert "reciprocal_rank_fusion" in src
        assert "rrf_score" in src
