"""Claim relations (#253).

The rules are the ported ones; these tests pin the guardrails that keep a
relation honest — a unit mismatch or a missing value must never be read as
agreement.
"""

from __future__ import annotations

from datetime import date

import pytest

from research_shared.relations import (
    CONTRADICT_DELTA,
    RELATION_VERSION,
    SUPPORT_DELTA,
    compare,
    dates_overlap,
    numeric_delta,
    same_claim_text,
)


class TestNumericDelta:
    def test_identical_values_are_zero(self):
        assert numeric_delta(10, 10) == 0.0

    def test_both_zero_is_safe(self):
        assert numeric_delta(0, 0) == 0.0

    def test_relative_not_absolute(self):
        # 1 vs 2 is a 50% difference, not a difference of 1.
        assert numeric_delta(1, 2) == pytest.approx(0.5)


class TestDateOverlap:
    def test_overlapping_spans(self):
        assert dates_overlap(date(2020, 1, 1), date(2021, 12, 31),
                             date(2021, 6, 1), date(2022, 6, 1)) is True

    def test_disjoint_spans(self):
        assert dates_overlap(date(2010, 1, 1), date(2010, 12, 31),
                             date(2020, 1, 1), date(2020, 12, 31)) is False

    def test_unknown_is_none_not_false(self):
        assert dates_overlap(None, None, date(2020, 1, 1), date(2020, 12, 31)) is None


class TestCompare:
    def _pair(self, **overrides):
        base = {
            "a_value": 4.2, "a_unit": "percent",
            "a_start": date(2023, 1, 1), "a_end": date(2023, 12, 31),
            "b_value": 4.3, "b_unit": "percent",
            "b_start": date(2023, 1, 1), "b_end": date(2023, 12, 31),
        }
        base.update(overrides)
        return compare(**base)

    def test_close_values_support(self):
        decision = self._pair()
        assert decision.relation == "supports"
        assert 0.9 < decision.strength <= 1.0

    def test_distant_values_contradict(self):
        decision = self._pair(b_value=9.0)
        assert decision.relation == "contradicts"
        assert decision.strength >= CONTRADICT_DELTA

    def test_middle_band_is_undecided(self):
        decision = self._pair(b_value=5.0)
        assert decision.relation is None
        assert decision.reason == "difference_in_undecided_band"

    def test_unit_mismatch_never_agrees(self):
        decision = self._pair(b_unit="people")
        assert decision.relation is None
        assert decision.reason == "unit_mismatch"

    def test_missing_value_never_agrees(self):
        decision = self._pair(b_value=None)
        assert decision.relation is None
        assert decision.reason == "missing_numeric_value"

    def test_disjoint_dates_block_support(self):
        decision = self._pair(b_start=date(1990, 1, 1), b_end=date(1990, 12, 31))
        assert decision.relation is None
        assert decision.reason == "date_spans_do_not_overlap"

    def test_thresholds_are_inclusive_at_the_boundary(self):
        # 10% apart sits exactly on the support boundary.
        decision = self._pair(a_value=100.0, b_value=90.0)
        assert decision.relation == "supports"
        assert SUPPORT_DELTA == pytest.approx(0.10)

    def test_version_is_exposed(self):
        assert RELATION_VERSION

class TestSubjectGate:
    """A shared unit is not a shared subject."""

    def test_unrelated_subjects_never_contradict(self):
        decision = compare(
            similarity=0.62, a_value=5.0, a_unit="percent", b_value=80.0, b_unit="percent",
        )
        assert decision.relation is None
        assert decision.reason == "subjects_not_similar_enough"

    def test_close_subjects_can_contradict(self):
        decision = compare(
            similarity=0.95, a_value=5.0, a_unit="percent", b_value=80.0, b_unit="percent",
        )
        assert decision.relation == "contradicts"

class TestSameClaimText:
    """Only the number may differ for a numeric relation to be claimed."""

    def test_digits_only_difference_is_the_same_claim(self):
        assert same_claim_text("1 of 50 states names come from persons.",
                               "11 of 50 states names come from persons.")

    def test_different_subject_in_same_template_is_not(self):
        assert not same_claim_text(
            "About 42% of businesses in the Information sector are small",
            "In comparison, businesses in the Retail Trade sector are small",
        )

    def test_template_with_different_labels_is_not(self):
        assert not same_claim_text(
            "Hallucination: Hallucinated reasoning trace or facts",
            "False positive: Hallucinated reasoning trace or facts",
        )
