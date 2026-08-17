"""Tests for the persuasive-authority weighting model (slice #71).

The weighting model combines five bounded factor functions —
``hierarchy``, ``density``, ``recency``, ``fit``, ``treatment`` — with fixed
weights that sum to 1.0, and is exposed through
``LegalPlugin.weighting_models()``.
"""

from __future__ import annotations

from datetime import date

import pytest

from plugins.legal import LegalPlugin
from plugins.legal.weighting import (
    WEIGHTS,
    density,
    fit,
    hierarchy,
    persuasive_authority,
    recency,
    treatment,
)

# ---------------------------------------------------------------------------
# weights
# ---------------------------------------------------------------------------


class TestWeights:
    def test_weights_sum_to_exactly_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_all_five_factors_present(self):
        assert set(WEIGHTS) == {"hierarchy", "density", "recency", "fit", "treatment"}


# ---------------------------------------------------------------------------
# hierarchy
# ---------------------------------------------------------------------------


class TestHierarchy:
    @pytest.mark.parametrize("target", ["federal", "California", ""])
    def test_bounded(self, target):
        for court in (
            "Supreme Court of the United States",
            "California Supreme Court",
            "United States Court of Appeals for the Ninth Circuit",
            "United States District Court for the District of Delaware",
            "Unknown Court",
        ):
            assert 0.0 <= hierarchy(court, target) <= 1.0

    def test_federal_supreme_above_federal_district(self):
        supreme = hierarchy("Supreme Court of the United States", "federal")
        district = hierarchy(
            "United States District Court for the District of Delaware", "federal"
        )
        assert supreme > district

    def test_same_jurisdiction_bonus(self):
        same = hierarchy("California Supreme Court", "California")
        out = hierarchy("California Supreme Court", "New York")
        assert same > out


# ---------------------------------------------------------------------------
# density
# ---------------------------------------------------------------------------


class TestDensity:
    def test_zero_citations(self):
        assert density({}) == 0.0

    def test_saturates_at_cap(self):
        assert density({"metadata": {"citation_count": 100}}) == 1.0
        assert density({"metadata": {"citation_count": 500}}) == 1.0

    def test_partial(self):
        assert density({"metadata": {"citation_count": 50}}) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# recency
# ---------------------------------------------------------------------------


class TestRecency:
    def test_recent_decision_scores_high(self):
        assert recency("2026-01-01", as_of=date(2026, 1, 1)) == 1.0

    def test_old_decision_scores_low(self):
        assert recency("1970-01-01", as_of=date(2026, 1, 1)) < 0.5

    def test_unknown_date_is_neutral(self):
        assert recency(None) == 0.5

    def test_bounded_and_monotonic(self):
        as_of = date(2026, 1, 1)
        newer = recency("2020-01-01", as_of=as_of)
        older = recency("1990-01-01", as_of=as_of)
        assert 0.0 <= older <= newer <= 1.0


# ---------------------------------------------------------------------------
# fit
# ---------------------------------------------------------------------------


class TestFit:
    def test_exact_match(self):
        case = {
            "metadata": {"subject": "qualified immunity", "title": "Smith v. Jones"}
        }
        assert fit(case, "qualified immunity") == 1.0

    def test_partial_match(self):
        case = {"metadata": {"subject": "qualified immunity"}}
        score = fit(case, "qualified immunity and excessive force")
        assert 0.0 < score < 1.0

    def test_no_match(self):
        case = {"metadata": {"subject": "tax law"}}
        assert fit(case, "qualified immunity") == 0.0

    def test_empty_issue_is_neutral(self):
        assert fit({}, "") == 0.5


# ---------------------------------------------------------------------------
# treatment
# ---------------------------------------------------------------------------


class TestTreatment:
    def test_strong_green(self):
        assert treatment({"state": "STRONG_GREEN"}) == 1.0

    def test_citator_red(self):
        assert treatment({"state": "CITATOR_RED"}) == 0.0

    def test_none_is_neutral(self):
        assert treatment(None) == 0.5

    def test_unknown_state_is_neutral(self):
        assert treatment({"state": "SOMETHING_NEW"}) == 0.5


# ---------------------------------------------------------------------------
# persuasive_authority
# ---------------------------------------------------------------------------


class TestPersuasiveAuthority:
    def test_bounded_zero_to_one(self):
        case = {
            "metadata": {
                "court": "Supreme Court of the United States",
                "decided_date": "2026-01-01",
                "citation_count": 100,
                "subject": "qualified immunity",
            }
        }
        context = {
            "target_jurisdiction": "federal",
            "issue": "qualified immunity",
            "reconciliation": {"state": "STRONG_GREEN"},
        }
        assert 0.0 <= persuasive_authority(case, context) <= 1.0

    def test_weights_are_applied(self):
        case = {
            "metadata": {
                "court": "Supreme Court of the United States",
                "decided_date": "2026-01-01",
                "citation_count": 100,
                "subject": "qualified immunity",
            }
        }
        context = {
            "target_jurisdiction": "federal",
            "issue": "qualified immunity",
            "reconciliation": {"state": "STRONG_GREEN"},
        }
        expected = (
            WEIGHTS["hierarchy"]
            * hierarchy(case["metadata"]["court"], context["target_jurisdiction"])
            + WEIGHTS["density"] * density(case)
            + WEIGHTS["recency"] * recency(case["metadata"]["decided_date"])
            + WEIGHTS["fit"] * fit(case, context["issue"])
            + WEIGHTS["treatment"] * treatment(context["reconciliation"])
        )
        assert persuasive_authority(case, context) == pytest.approx(expected)

    def test_default_context_does_not_crash(self):
        assert 0.0 <= persuasive_authority({}) <= 1.0


# ---------------------------------------------------------------------------
# plugin wiring
# ---------------------------------------------------------------------------


class TestPluginWiring:
    def test_weighting_models_returns_persuasive_authority(self):
        models = LegalPlugin().weighting_models()
        assert "persuasive_authority" in models
        assert callable(models["persuasive_authority"])

    def test_model_callable_bounded(self):
        fn = LegalPlugin().weighting_models()["persuasive_authority"]
        assert 0.0 <= fn({}) <= 1.0
