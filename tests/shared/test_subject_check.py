"""The words can all be there while the document is about something else.

Defect this pins: "When did Saimon move off Heroku?" returned a Coolify research
note because it is the only chunk in the corpus containing the word Heroku — a
comparison mention, not an answer. Coverage cannot see the difference; a check on
whether the document concerns the question's rarest subject can.
"""

from research_shared.rerank import RerankConfig, rerank


def cand(title: str, body: str, similarity: float = 0.95, path: str = "") -> dict:
    return {
        "id": title[:10],
        "title": title,
        "body": body,
        "similarity": similarity,
        "metadata": {"path": path},
    }


DF = {"saimon": 1600, "move": 500, "heroku": 1, "coolify": 40, "paas": 90}

QUESTION = "When did Saimon move off Heroku?"


class TestSubjectCheck:
    def test_a_comparison_mention_is_not_an_answer(self):
        note = cand(
            "Coolify - Self-Hosted PaaS",
            "Coolify is a self-hosted PaaS. Alternatives include Heroku, which "
            "charges per dyno. Saimon runs elsewhere; the move was not recorded.",
        )
        outcome = rerank(QUESTION, [note], RerankConfig(), corpus_df=DF, corpus_size=24000)
        assert outcome.fail_safe_fired
        assert outcome.abstain_reason == "subject"
        assert outcome.ranked == []

    def test_a_document_about_the_subject_passes(self):
        note = cand(
            "Heroku to Hetzner migration",
            "Saimon moved off Heroku in March and now runs on Hetzner.",
            path="governance/heroku-migration.md",
        )
        outcome = rerank(QUESTION, [note], RerankConfig(), corpus_df=DF, corpus_size=24000)
        assert outcome.abstain_reason != "subject"
        assert outcome.ranked

    def test_repeated_mentions_count_as_being_about_it(self):
        note = cand(
            "Infrastructure notes",
            "We left Heroku. Heroku billed per dyno and the Saimon move saved money.",
        )
        outcome = rerank(QUESTION, [note], RerankConfig(), corpus_df=DF, corpus_size=24000)
        assert outcome.abstain_reason != "subject"

    def test_a_common_rarest_term_skips_the_check(self):
        """No single subject to test when every word is common."""
        common = {"saimon": 1600, "move": 500, "heroku": 900, "off": 1000}
        note = cand("Infrastructure notes", "Saimon will move off the current host later.")
        outcome = rerank(QUESTION, [note], RerankConfig(), corpus_df=common, corpus_size=24000)
        assert outcome.abstain_reason != "subject"

    def test_the_check_can_be_turned_off(self):
        note = cand("Coolify - Self-Hosted PaaS", "Alternatives include Heroku.")
        outcome = rerank(
            QUESTION, [note], RerankConfig(subject_max_df=0),
            corpus_df=DF, corpus_size=24000,
        )
        assert outcome.abstain_reason != "subject"
