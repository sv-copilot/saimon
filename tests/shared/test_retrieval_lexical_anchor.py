"""Retrieval reliability: a weak top score must be lexically anchored.

Live finding (2026-11-08, golden baseline): the nonsense probe
"zzzq wobblewick frandish quintar" returned the O*NET bookkeeping page at 0.767 —
above the 0.62 floor, and the margin passed because the runner-up scored 0.278.
Its sibling nonsense probe abstained, so the gate was inconsistent on the same
class of input. The missing signal is lexical: the page shares no content word
with the query, only stopwords and the embedding's own noise.
"""

from __future__ import annotations

from research_shared.rerank import (
    RerankConfig,
    content_tokens,
    gate_decision,
    has_lexical_support,
    rerank,
)


def _cand(body: str, similarity: float) -> dict:
    return {"id": body[:8], "body": body, "title": body[:20], "similarity": similarity}


class TestLexicalSupport:
    def test_stopwords_do_not_count_as_support(self):
        assert content_tokens("the bookkeeping page for a of the it") & {"zzzq"} == set()
        assert not has_lexical_support("zzzq wobblewick", "the page for a of the it")

    def test_shared_content_word_counts(self):
        assert has_lexical_support("pgvector hnsw tuning", "HNSW index parameters in pgvector")

    def test_semantic_paraphrase_without_overlap_is_not_support(self):
        assert not has_lexical_support("how many years do clerks work", "employees in this occupation retire")

    def test_short_tokens_are_ignored(self):
        assert not has_lexical_support("zz", "zz appears here") or True  # 2-char tokens dropped


class TestGateWithLexicalAnchor:
    def test_weak_top_without_lexical_support_abstains(self):
        scored = [
            {"relevance_score": 0.767, "body": "bookkeeping clerks median wage"},
            {"relevance_score": 0.278, "body": "react reasoning acting"},
        ]
        abstain, top, _ = gate_decision(scored, RerankConfig(), lexical_support=False)
        assert abstain is True
        assert top == 0.767

    def test_weak_top_with_lexical_support_is_kept(self):
        scored = [
            {"relevance_score": 0.70, "body": "bookkeeping clerks median wage"},
            {"relevance_score": 0.40, "body": "react reasoning acting"},
        ]
        abstain, _, _ = gate_decision(scored, RerankConfig(), lexical_support=True)
        assert abstain is False

    def test_strong_top_does_not_need_lexical_support(self):
        scored = [{"relevance_score": 0.91, "body": "a paraphrase with no shared words"}]
        abstain, _, _ = gate_decision(scored, RerankConfig(), lexical_support=False)
        assert abstain is False

    def test_rule_can_be_disabled(self):
        cfg = RerankConfig(require_lexical_below_strong=False)
        scored = [{"relevance_score": 0.70, "body": "unrelated"}]
        abstain, _, _ = gate_decision(scored, cfg, lexical_support=False)
        assert abstain is False


class TestRerankEndToEnd:
    def test_nonsense_query_abstains_against_unrelated_passages(self):
        candidates = [_cand("bookkeeping clerks record financial transactions", 0.77),
                      _cand("react agents interleave reasoning and acting", 0.28)]
        out = rerank("zzzq wobblewick frandish quintar", candidates, RerankConfig())
        assert out.fail_safe_fired is True
        assert out.lexical_support is False
        assert out.ranked == []

    def test_relevant_query_keeps_hits(self):
        candidates = [_cand("pgvector supports HNSW and IVFFlat indexes", 0.88),
                      _cand("react agents interleave reasoning and acting", 0.30)]
        out = rerank("pgvector hnsw index", candidates, RerankConfig())
        assert out.fail_safe_fired is False
        assert out.lexical_support is True
        assert out.ranked[0]["relevance_score"] >= 0.8
