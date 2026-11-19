"""Corpus statistics must decide what a passage can be said to cover.

Defect this pins: the coverage gate counted matched tokens as equal, so
"When did Saimon move off Heroku?" cleared the floor on `saimon` alone — a word
that appears in thousands of chunks — while `heroku` appears in none. The passage
was then returned as evidence for a migration that never happened.
"""

from research_shared.rerank import RerankConfig, lexical_coverage, rerank
from research_shared.term_stats import idf_weights


def cand(body: str, similarity: float = 0.9) -> dict:
    return {"id": body[:10], "title": body[:40], "body": body, "similarity": similarity}


class TestWeightedCoverage:
    def test_a_common_word_alone_does_not_cover_the_query(self):
        weights = idf_weights({"saimon": 9000, "heroku": 0}, 10000, ["saimon", "heroku"])
        coverage = lexical_coverage("Saimon Heroku", "Saimon runs on Hetzner", weights)
        assert coverage < 0.35

    def test_both_words_present_covers_it(self):
        weights = idf_weights({"saimon": 9000, "heroku": 0}, 10000, ["saimon", "heroku"])
        coverage = lexical_coverage("Saimon Heroku", "Saimon and Heroku", weights)
        assert coverage == 1.0

    def test_absent_term_outweighs_a_common_one(self):
        weights = idf_weights({"saimon": 9000, "heroku": 0}, 10000, ["saimon", "heroku"])
        assert weights["heroku"] > weights["saimon"] * 2

    def test_unweighted_behaviour_is_unchanged(self):
        assert lexical_coverage("ukulele tuning", "prompt tuning") == 0.5


class TestAbsentTermRefuses:
    def test_a_term_the_corpus_never_mentions_fires_the_gate(self):
        candidates = [cand("Saimon runs on Hetzner with docker compose.", 0.95)]
        outcome = rerank(
            "When did Saimon move off Heroku?",
            candidates,
            RerankConfig(),
            corpus_df={"saimon": 9000, "move": 400, "heroku": 0},
            corpus_size=10000,
        )
        assert outcome.fail_safe_fired
        assert outcome.abstain_reason == "absent_term"
        assert outcome.ranked == []

    def test_a_measured_term_that_exists_does_not_fire_it(self):
        candidates = [cand("Saimon runs on Hetzner with docker compose.", 0.95)]
        outcome = rerank(
            "Where does Saimon run?",
            candidates,
            RerankConfig(),
            corpus_df={"saimon": 9000, "run": 800, "hetzner": 120},
            corpus_size=10000,
        )
        assert outcome.abstain_reason != "absent_term"

    def test_unmeasured_terms_are_not_called_absent(self):
        """A reformulated query's new words were never counted; guessing refuses it."""
        candidates = [cand("Saimon runs on Hetzner with docker compose.", 0.95)]
        outcome = rerank(
            "Where does the knowledge service live?",
            candidates,
            RerankConfig(),
            corpus_df={"knowledge": 900, "service": 1200},
            corpus_size=10000,
        )
        assert outcome.abstain_reason != "absent_term"


class TestWeightsCannotRefuseEverything:
    """A negative weight made every query abstain — the gate looked strict, not broken."""

    def test_weights_are_positive_whatever_the_frequency(self):
        weights = idf_weights(
            {"saimon": 1600, "knowledge": 2000, "heroku": 1}, 24000,
            ["saimon", "knowledge", "heroku"],
        )
        assert all(value > 0.0 for value in weights.values())

    def test_a_frequent_term_still_covers_its_own_passage(self):
        weights = idf_weights({"saimon": 1600}, 24000, ["saimon"])
        assert lexical_coverage("saimon", "saimon runs on hetzner", weights) == 1.0

    def test_no_corpus_size_means_equal_weights(self):
        weights = idf_weights({"a": 9000, "b": 3}, None, ["a", "b"])
        assert weights == {"a": 1.0, "b": 1.0}
