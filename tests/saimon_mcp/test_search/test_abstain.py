"""RED tests for SAIMON-RETRIEVAL-ABSTAIN-1 (#234).

The measured defect: ``DEFAULT_MIN_RELEVANCE`` (0.25) sits below the reranker's
nonsense semantic-similarity baseline (~0.58-0.6), so an unrelated query fills
every slot with top-N noise instead of abstaining.  A floor alone cannot fix it
either: a weak-but-real hit can land at ~0.65, close to the noise band, so the
gate also needs a margin over the runner-up.
"""

from research_shared.rerank import (
    DEFAULT_MIN_MARGIN,
    DEFAULT_MIN_RELEVANCE,
    RerankConfig,
    gate_decision,
    rerank,
)

UNRELATED_TEXT = "budget variance worksheet for the landscaping crew"


def _candidate(similarity: float, text: str = UNRELATED_TEXT) -> dict:
    return {"id": "n1", "title": "t", "body": text, "similarity": similarity}


class TestFloorGate:
    def test_nonsense_query_abstains(self) -> None:
        """A query with no lexical overlap and noise-level similarity returns nothing."""
        candidates = [_candidate(0.60) for _ in range(5)]
        outcome = rerank("xzqv plorbinate frobnication quuxil", candidates)

        assert outcome.fail_safe_fired is True
        assert outcome.ranked == []

    def test_floor_is_above_the_nonsense_baseline(self) -> None:
        assert DEFAULT_MIN_RELEVANCE > 0.31  # 0.5 lexical*0 + 0.5 semantic*0.62

    def test_similarity_above_the_old_floor_no_longer_passes(self) -> None:
        """The old gate (0.25) kept this; the new one must not."""
        outcome = rerank("quantum chromodynamics lattice", [_candidate(0.55)])
        assert outcome.fail_safe_fired is True


class TestMarginGate:
    def test_close_call_abstains(self) -> None:
        """Top clear of the floor but only 0.055 ahead of the runner-up."""
        fire, top, gap = gate_decision(
            [{"relevance_score": 0.70}, {"relevance_score": 0.645}],
            RerankConfig(),
        )
        assert fire is True
        assert top == 0.70
        assert round(gap, 3) == 0.055

    def test_clear_winner_keeps(self) -> None:
        fire, _, gap = gate_decision(
            [{"relevance_score": 0.70}, {"relevance_score": 0.55}],
            RerankConfig(),
        )
        assert fire is False
        assert round(gap, 3) == 0.15

    def test_single_candidate_is_judged_on_the_floor_alone(self) -> None:
        fire, _, _ = gate_decision([{"relevance_score": 0.90}], RerankConfig())
        assert fire is False

    def test_margin_is_configurable(self) -> None:
        fire, _, _ = gate_decision(
            [{"relevance_score": 0.70}, {"relevance_score": 0.645}],
            RerankConfig(min_margin=0.02),
        )
        assert fire is False

    def test_default_margin_is_non_zero(self) -> None:
        assert DEFAULT_MIN_MARGIN > 0.0


class TestRealHitSurvives:
    def test_lexical_hit_is_kept(self) -> None:
        """A real hit with strong lexical overlap must not be clipped by the floor."""
        candidates = [
            {"id": "a", "title": "Tufte data ink ratio", "body": "data ink ratio", "similarity": 0.8},
            {"id": "b", "title": "Unrelated budgeting", "body": UNRELATED_TEXT, "similarity": 0.55},
        ]
        outcome = rerank("Tufte data ink ratio", candidates)

        assert outcome.fail_safe_fired is False
        assert outcome.ranked
        assert outcome.ranked[0]["id"] == "a"
        assert "relevance_score" in outcome.ranked[0]


class TestOutcomeCarriesTheEvidence:
    def test_outcome_reports_gap(self) -> None:
        outcome = rerank(
            "Tufte data ink ratio",
            [
                {"id": "a", "title": "Tufte data ink ratio", "body": "data ink ratio", "similarity": 0.8},
                {"id": "b", "title": "Unrelated budgeting", "body": UNRELATED_TEXT, "similarity": 0.1},
            ],
        )
        assert outcome.margin_gap > 0.0
        assert outcome.second_score >= 0.0
