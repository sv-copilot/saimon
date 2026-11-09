"""Bounded evidence priors (#273).

A prior must be able to break a tie without being able to bury evidence. These
tests pin the cap, the missing-input behaviour, and the dissent guardrail.
"""

from __future__ import annotations

import pytest

from research_shared.priors import (
    MAX_BONUS,
    adjust_score,
    apply_priors,
    prior_contribution,
)


class TestContribution:
    def test_no_inputs_contribute_nothing(self):
        bonus, detail = prior_contribution(quality=None, primacy=None)
        assert bonus == 0.0
        assert detail["reason"] == "no_prior_inputs"

    def test_high_quality_helps(self):
        bonus, _ = prior_contribution(quality=0.9, primacy=None)
        assert bonus > 0

    def test_low_quality_hurts(self):
        bonus, _ = prior_contribution(quality=0.2, primacy=None)
        assert bonus < 0

    def test_near_primary_helps_and_far_hurts(self):
        near, _ = prior_contribution(quality=None, primacy=0.05)
        far, _ = prior_contribution(quality=None, primacy=0.95)
        assert near > 0 > far

    def test_bonus_is_capped(self):
        bonus, detail = prior_contribution(quality=1.0, primacy=0.0)
        assert bonus == pytest.approx(MAX_BONUS)
        assert detail["capped"] is True

    def test_cap_holds_in_both_directions(self):
        worst, _ = prior_contribution(quality=0.0, primacy=1.0)
        assert worst == pytest.approx(-MAX_BONUS)


class TestAdjustScore:
    def test_adjustment_is_multiplicative_and_bounded(self):
        low, _ = adjust_score(0.8, quality=0.0, primacy=1.0)
        high, _ = adjust_score(0.8, quality=1.0, primacy=0.0)
        assert low == pytest.approx(0.8 * (1 - MAX_BONUS), rel=1e-3)
        assert high == pytest.approx(0.8 * (1 + MAX_BONUS), rel=1e-3)

    def test_unscored_rows_are_unchanged(self):
        score, detail = adjust_score(0.77, quality=None, primacy=None)
        assert score == 0.77
        assert detail["bonus"] == 0.0


class TestApply:
    def _rows(self):
        return [
            {"id": "a", "relevance_score": 0.80, "quality_score": 0.40, "primacy_distance_score": 0.80},
            {"id": "b", "relevance_score": 0.78, "quality_score": 0.90, "primacy_distance_score": 0.10},
        ]

    def test_quality_can_flip_a_close_pair(self):
        ranked = apply_priors(self._rows())
        assert ranked[0]["id"] == "b"

    def test_original_scores_are_preserved_for_explanation(self):
        ranked = apply_priors(self._rows())
        for row in ranked:
            assert "relevance_score_before_prior" in row
            assert row["prior"]["bonus"] != 0.0

    def test_a_clear_winner_is_not_overturned(self):
        rows = [
            {"id": "strong", "relevance_score": 0.95, "quality_score": 0.0, "primacy_distance_score": 1.0},
            {"id": "weak", "relevance_score": 0.50, "quality_score": 1.0, "primacy_distance_score": 0.0},
        ]
        assert apply_priors(rows)[0]["id"] == "strong"

    def test_rows_without_priors_keep_their_order(self):
        rows = [
            {"id": "a", "relevance_score": 0.9},
            {"id": "b", "relevance_score": 0.8},
        ]
        assert [r["id"] for r in apply_priors(rows)] == ["a", "b"]
