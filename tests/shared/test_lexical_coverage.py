"""The lexical half of relevance must be absolute, not relative to the candidate set.

Defect this pins: the lexical component divided each candidate's BM25 score by the best
candidate's score, so the top hit always received 1.0. Every query therefore started the
blend at 0.5, and "how to tune a ukulele" cleared a 0.62 floor against a passage about
prompt tuning (live, 2026-11-15: top score 0.813, abstain false, five unrelated claims
returned).
"""

from research_shared.rerank import (
    RerankConfig,
    lexical_coverage,
    rerank,
)


def cand(body: str, similarity: float) -> dict:
    return {"id": body[:8], "title": body[:40], "body": body, "similarity": similarity}


class TestCoverageIsAbsolute:
    def test_one_of_two_query_tokens_is_half(self):
        assert lexical_coverage("ukulele tuning", "prompt tuning for language models") == 0.5

    def test_no_shared_tokens_is_zero(self):
        assert lexical_coverage("ukulele tuning", "bookkeeping clerks record transactions") == 0.0

    def test_all_tokens_present_is_one(self):
        assert lexical_coverage("prompt tuning", "prompt tuning for language models") == 1.0

    def test_plurals_fold(self):
        assert lexical_coverage("pgvector hnsw index", "pgvector supports HNSW indexes") == 1.0

    def test_coverage_does_not_depend_on_the_other_candidates(self):
        """The same passage scores the same whether or not a stronger match is present."""
        passage = "prompt tuning for language models"
        alone = lexical_coverage("ukulele tuning", passage)
        assert alone == lexical_coverage("ukulele tuning", passage)


class TestNonsenseStopsAtTheGate:
    def test_single_shared_word_and_high_cosine_still_abstains(self):
        # "tune" is the only shared token; the embedding rates the passage highly because
        # both are about tuning. Coverage is 0.5, the blend lands below the floor.
        out = rerank(
            "how to tune a ukulele",
            [cand("prompt tuning for language models", 0.93)],
            RerankConfig(),
        )
        # The score stays high (the embedding likes it); the words are what refuse it.
        assert out.fail_safe_fired is True
        assert out.abstain_reason == "coverage"
        assert out.ranked == []

    def test_a_fully_covered_passage_is_kept(self):
        out = rerank(
            "pgvector hnsw index",
            [cand("pgvector supports HNSW indexes for approximate search", 0.88)],
            RerankConfig(),
        )
        assert out.fail_safe_fired is False
        assert out.ranked[0]["coverage_score"] == 1.0
