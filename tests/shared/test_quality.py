"""Quality scores (#255).

Quality and primacy are different questions and must not collapse into one
another: a first-hand blog post is near-primary and low quality; a peer-reviewed
review is far from primary and highly reliable.
"""

from __future__ import annotations

from research_shared.quality import (
    QUALITY_VERSION,
    extraction_score,
    is_scoreable,
    observation_quality,
    relation_balance,
    reputation_score,
    source_quality,
    structure_score,
    verification_score,
)


class TestComponents:
    def test_reputation_ordering(self):
        assert reputation_score("A") > reputation_score("B") > reputation_score("C") > reputation_score("unknown")

    def test_unknown_reputation_is_not_penalised_to_zero(self):
        assert reputation_score(None) > 0.0

    def test_verification_ordering(self):
        assert verification_score("supported") > verification_score("mixed")
        assert verification_score("mixed") > verification_score("insufficient_evidence")
        assert verification_score("insufficient_evidence") > verification_score("contradicted")
        assert verification_score("error") == 0.0

    def test_structure_rewards_fields(self):
        none = structure_score(has_value=False, has_date=False, has_unit=False)
        some = structure_score(has_value=True, has_date=True, has_unit=False)
        all_ = structure_score(has_value=True, has_date=True, has_unit=True)
        assert none < some < all_

    def test_missing_extraction_confidence_is_a_default_not_zero(self):
        assert extraction_score(None) == 0.55

    def test_low_signal_claims_are_not_defaulted_to_mid(self):
        assert extraction_score(None, low_signal=True) < extraction_score(None)

    def test_extraction_is_bounded(self):
        assert extraction_score(5.0) == 1.0
        assert extraction_score(-1.0) == 0.10 or extraction_score(-1.0) == 0.55


class TestObservationQuality:
    def test_supported_structured_claim_beats_an_unsupported_prose_one(self):
        good, _ = observation_quality(extraction=0.9, verification=verification_score("supported"),
                                      reputation=reputation_score("A"),
                                      structure=structure_score(has_value=True, has_date=True, has_unit=True))
        weak, _ = observation_quality(extraction=0.4, verification=verification_score("insufficient_evidence"),
                                      reputation=reputation_score("unknown"),
                                      structure=structure_score(has_value=False, has_date=False, has_unit=False))
        assert good > weak

    def test_breakdown_carries_every_component(self):
        _, breakdown = observation_quality(extraction=0.5, verification=0.5, reputation=0.5, structure=0.5)
        assert breakdown["version"] == QUALITY_VERSION
        for key in ("extraction_component", "verification_component",
                    "reputation_component", "structure_component"):
            assert key in breakdown

    def test_score_is_bounded(self):
        score, _ = observation_quality(extraction=1, verification=1, reputation=1, structure=1)
        assert score <= 0.99


class TestRelationBalance:
    def test_no_relations_is_neutral(self):
        assert relation_balance(0, 0) == 0.5

    def test_support_raises_and_dissent_lowers(self):
        assert relation_balance(5, 0) > 0.5
        assert relation_balance(0, 5) < 0.5

    def test_bounded(self):
        assert 0.0 <= relation_balance(100, 0) <= 1.0
        assert 0.0 <= relation_balance(0, 100) <= 1.0


class TestSourceQuality:
    def test_strong_source_beats_weak(self):
        strong, _ = source_quality(reputation=0.9, mean_observation=0.8, verification_health=0.9,
                                   extraction_health=0.9, balance=0.7)
        weak, _ = source_quality(reputation=0.45, mean_observation=0.4, verification_health=0.3,
                                 extraction_health=0.4, balance=0.4)
        assert strong > weak

    def test_breakdown_and_bounds(self):
        score, breakdown = source_quality(reputation=0.9, mean_observation=0.9, verification_health=1,
                                          extraction_health=1, balance=1)
        assert score <= 0.99
        assert breakdown["version"] == QUALITY_VERSION
        assert "relation_balance_component" in breakdown

class TestScoreability:
    """Refusing to score beats scoring from defaults."""

    def test_full_coverage_is_scoreable(self):
        ok, reason = is_scoreable(verification_coverage=1.0, extraction_coverage=1.0)
        assert ok and reason == "ok"

    def test_no_verification_data_blocks_scoring(self):
        ok, reason = is_scoreable(verification_coverage=0.0, extraction_coverage=1.0)
        assert not ok and "verification_coverage" in reason

    def test_no_extraction_data_blocks_scoring(self):
        ok, reason = is_scoreable(verification_coverage=1.0, extraction_coverage=0.0)
        assert not ok and "extraction_coverage" in reason
