"""Near-duplicate claim collapse (SAIMON-CLAIM-NEAR-DUP-1).

Exact-hash dedupe let paraphrases from two papers survive as separate knowledge:
"accuracy degrades 30% in long contexts" and "accuracy drops 30% for long
contexts" are one fact. The cascade must merge those while never merging claims
that differ in a number.
"""

from __future__ import annotations

from research_shared.claims import (
    claim_text_hash,
    claims_near_duplicate,
    normalise_claim,
)


class TestNormalisation:
    def test_collapses_whitespace_and_case(self):
        assert normalise_claim("  Accuracy   DEGRADES 30%. ") == "accuracy degrades 30%."

    def test_hash_is_stable_for_formatting_noise(self):
        assert claim_text_hash("A  claim.") == claim_text_hash("a claim.")


class TestNearDuplicate:
    def test_paraphrase_is_a_duplicate(self):
        a = "Accuracy degrades by 30% when evidence sits in the middle of a long context."
        b = "Accuracy degrades by 30% when evidence is in the middle of a long context."
        assert claims_near_duplicate(a, b)

    def test_number_difference_is_not_a_duplicate(self):
        a = "Accuracy degrades by 30% when evidence sits in the middle of a long context."
        b = "Accuracy degrades by 31% when evidence sits in the middle of a long context."
        assert not claims_near_duplicate(a, b)

    def test_containment_of_a_long_shorter_text(self):
        long = (
            "The service handled 1200 requests per minute during the load test while "
            "the queue stayed below ten messages."
        )
        short = "The service handled 1200 requests per minute during the load test"
        assert claims_near_duplicate(long, short)

    def test_short_containment_is_not_enough(self):
        assert not claims_near_duplicate(
            "Revenue grew 12% in 2024 and margins held.",
            "Revenue grew 12% in 2024.",
        )

    def test_unrelated_claims_are_not_duplicates(self):
        assert not claims_near_duplicate(
            "Entity resolution uses blocking then matching.",
            "Workers compensation premiums depend on payroll and claims history.",
        )

    def test_empty_input_is_not_a_duplicate(self):
        assert not claims_near_duplicate("", "anything")
        assert not claims_near_duplicate("anything", "   ")
