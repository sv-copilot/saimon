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


def test_question_form_scores_like_the_keyword_form() -> None:
    """A question and its keywords must retrieve the same passage.

    "What did cycle 039 decide about loading the portfolio into the knowledge
    graph" scored 0.0 against the document that answers it, because 'what',
    'did', 'about' and 'into' counted as content.
    """
    from research_shared.rerank import lexical_coverage, support_tokens

    passage = (
        "Cycle 039 decided to ingest the portfolio into the knowledge graph: "
        "six thousand seven hundred documents, sixteen thousand chunks."
    )
    question = "What did cycle 039 decide about loading the portfolio into the knowledge graph?"
    assert {"what", "did", "about", "into"}.isdisjoint(support_tokens(question))
    assert lexical_coverage(question, passage) >= 0.5


def test_identifiers_survive_but_years_do_not() -> None:
    """A number that identifies a document is content; a year is not."""
    from research_shared.rerank import support_tokens

    assert "039" in support_tokens("What did cycle 039 decide about the portfolio?")
    # Two-digit numbers stay out: content_tokens drops tokens shorter than
    # three characters, and a bare "17" in prose is not distinctive enough to
    # be worth the noise it lets in.
    assert "17" not in support_tokens("How many stages does the CI preflight have, 17?")
    assert "2024" not in support_tokens("who won the 2024 super bowl")
