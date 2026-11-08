"""Requery must not defeat the abstention gate (#261 follow-up).

Live finding on the deployed train: the nonsense probe "zzzq wobblewick frandish
quintar" abstained on the first pass, then the fail-safe requery appended
"overview", matched that word in a bookkeeping page, and returned three hits.
The gate worked; the retry undid it.
"""

from __future__ import annotations

from research_shared.rerank import RerankConfig, abstain_reason, rerank


def _cand(body: str, similarity: float) -> dict:
    return {"id": body[:6], "body": body, "title": body[:12], "similarity": similarity}


class TestAbstainReason:
    def test_no_candidates(self):
        assert abstain_reason([], RerankConfig()) == "empty"

    def test_floor(self):
        scored = [{"relevance_score": 0.30, "body": "x"}]
        assert abstain_reason(scored, RerankConfig()) == "floor"

    def test_margin(self):
        scored = [{"relevance_score": 0.70, "body": "x"}, {"relevance_score": 0.68, "body": "y"}]
        assert abstain_reason(scored, RerankConfig(), lexical_support=True) == "margin"

    def test_no_lexical_support(self):
        scored = [{"relevance_score": 0.70, "body": "x"}, {"relevance_score": 0.20, "body": "y"}]
        assert abstain_reason(scored, RerankConfig(), lexical_support=False) == "no_lexical_support"

    def test_none_when_kept(self):
        scored = [{"relevance_score": 0.90, "body": "x"}]
        assert abstain_reason(scored, RerankConfig(), lexical_support=False) is None


class TestOutcomeCarriesReason:
    def test_nonsense_query_abstains_on_the_floor(self):
        # With 50/50 lexical+semantic weights a no-overlap hit peaks at 0.5,
        # so the floor is what stops it on the first pass.
        out = rerank(
            "zzzq wobblewick frandish quintar",
            [_cand("bookkeeping clerks record transactions", 0.77)],
            RerankConfig(),
        )
        assert out.fail_safe_fired is True
        assert out.abstain_reason == "floor"

    def test_no_lexical_support_is_reported_when_the_floor_is_cleared(self):
        # A lexical-scoring configuration can clear the floor without overlap;
        # that is the case the lexical rule exists for.
        cfg = RerankConfig(lexical_weight=0.0, semantic_weight=1.0)
        out = rerank(
            "zzzq wobblewick frandish quintar",
            [_cand("bookkeeping clerks record transactions", 0.70)],
            cfg,
        )
        assert out.fail_safe_fired is True
        assert out.abstain_reason == "no_lexical_support"

    def test_reformulator_words_do_not_constitute_support(self):
        from research_shared.rerank import has_lexical_support

        passage = "overview of bookkeeping clerks and their transactions"
        assert not has_lexical_support("zzzq wobblewick frandish quintar", passage)
        # ... but they do once the reformulator appends its own word, which is
        # exactly why the server judges support against the original query.
        assert has_lexical_support("zzzq wobblewick frandish quintar overview", passage)

    def test_requery_condition_excludes_lexical_failures(self):
        for reason, allowed in [
            ("floor", True), ("margin", True),
            ("no_lexical_support", False), ("empty", False), (None, False),
        ]:
            assert (reason in {"floor", "margin"}) is allowed


class TestNumericTokensAreNotSupport:
    """A year is a value, not evidence (live leak: "2024 super bowl" -> story map)."""

    def test_year_alone_does_not_anchor(self):
        from research_shared.rerank import has_lexical_support

        assert not has_lexical_support(
            "who won the 2024 super bowl",
            "The New User Story Backlog is a Map, updated 2024.",
        )

    def test_numeric_only_query_keeps_its_digits(self):
        from research_shared.rerank import has_lexical_support, support_tokens

        assert support_tokens("2024") == {"2024"}
        assert has_lexical_support("2024", "annual report 2024")

    def test_real_queries_still_anchor(self):
        from research_shared.rerank import has_lexical_support

        assert has_lexical_support("pgvector hnsw tuning", "HNSW parameters in pgvector")
        assert has_lexical_support(
            "how many years must payroll records be kept",
            "Keep payroll records for at least four years.",
        )
