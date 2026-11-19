"""A question's number can be wrong, and the passage is what proves it.

Defect this pins: "Which twelve lifecycle states does a Drake slice have?" returned
documents about lifecycle states that never said twelve — the right subject with
the wrong premise in front of it. Nothing in ranking could notice, because every
word matched. A number the passage contradicts is a different kind of evidence and
has to be surfaced, not smoothed over.
"""

from research_shared.rerank import (
    RerankConfig,
    numeral_conflict,
    query_numerals,
    rerank,
)


def cand(title: str, body: str, similarity: float = 0.9) -> dict:
    return {"id": title[:10], "title": title, "body": body, "similarity": similarity}


class TestNumeralDetection:
    def test_digits_and_words_are_the_same_claim(self):
        assert query_numerals("12 lifecycle states") == query_numerals("twelve lifecycle states")

    def test_a_question_without_numbers_asks_nothing_numeric(self):
        assert query_numerals("How does the slice lifecycle work?") == set()

    def test_a_contradicting_number_is_found(self):
        conflict, numbers = numeral_conflict(
            "Which twelve lifecycle states does a slice have?",
            "Drake has eleven lifecycle states, from shaped to archived.",
        )
        assert conflict
        assert numbers == ["11"]

    def test_the_same_number_is_not_a_conflict(self):
        conflict, _ = numeral_conflict(
            "Which twelve lifecycle states does a slice have?",
            "Drake has twelve lifecycle states.",
        )
        assert not conflict

    def test_a_passage_with_no_numbers_is_silent_not_contradicting(self):
        conflict, _ = numeral_conflict(
            "Which twelve lifecycle states does a slice have?",
            "Lifecycle states are documented in the governance tree.",
        )
        assert not conflict


class TestPremiseIsSurfaced:
    def test_rerank_reports_the_conflict(self):
        passage = cand(
            "Slice lifecycle",
            "A Drake slice has eleven lifecycle states. Lifecycle states are "
            "described here and nowhere is a different count given.",
        )
        outcome = rerank(
            "Which twelve lifecycle states does a slice have?", [passage], RerankConfig()
        )
        assert outcome.premise_conflict
        assert outcome.conflicting_numbers == ["11"]

    def test_a_passage_stating_the_asked_number_is_not_flagged(self):
        passage = cand(
            "Slice lifecycle",
            "A Drake slice has twelve lifecycle states, listed below.",
        )
        outcome = rerank(
            "Which twelve lifecycle states does a slice have?", [passage], RerankConfig()
        )
        assert not outcome.premise_conflict

    def test_stating_the_number_outranks_merely_discussing_it(self):
        discussing = cand("Slice lifecycle", "Lifecycle states matter for governance.")
        stating = cand("Slice lifecycle table", "The twelve lifecycle states are listed.")
        outcome = rerank(
            "Which twelve lifecycle states does a slice have?",
            [discussing, stating],
            RerankConfig(),
        )
        assert outcome.ranked[0]["title"] == "Slice lifecycle table"
