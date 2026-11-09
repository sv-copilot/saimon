"""Evidence-first verification (SAIMON-VERIFY-EVIDENCE-ALGEBRA-1).

Measured before this slice: verify_claim took 45-73 s and returned `supported`
from two model self-grades with every `evidence_source` null. These tests pin the
replacement: a verdict is a function of stored evidence, and no evidence means
insufficient_evidence.
"""

from __future__ import annotations

import asyncio

import pytest

from research_shared.evidence import claim_tokens, collect_corpus_evidence, quote_from, support_score
from research_shared.verification import (
    CONTRADICTED,
    INSUFFICIENT,
    MIXED,
    SUPPORTED,
    ledger,
    resolve_status,
)


class TestClaimTokens:
    def test_drops_stopwords_and_short_tokens(self):
        assert claim_tokens("The HNSW index is fast") == ["hnsw", "index", "fast"]

    def test_deduplicates(self):
        assert claim_tokens("retrieval retrieval") == ["retrieval"]

    def test_empty(self):
        assert claim_tokens("") == []


class TestStatusAlgebra:
    def test_supported_floors_confidence(self):
        status, confidence, _ = resolve_status(supporting=2, contradicting=0, confidence=0.2)
        assert status == SUPPORTED
        assert confidence >= 0.65

    def test_contradicted_has_a_confidence_floor(self):
        # A contradiction is a positive finding: certainty about it is raised to
        # a floor, the same way `supported` is. (The weighting that DOWN-ranks a
        # contradicted claim lives in the ranking layer, not here.)
        status, confidence, _ = resolve_status(supporting=0, contradicting=2, confidence=0.1)
        assert status == CONTRADICTED
        assert confidence >= 0.35

    def test_mixed_when_both(self):
        status, _, _ = resolve_status(supporting=1, contradicting=1, confidence=0.7)
        assert status == MIXED

    def test_no_evidence_is_insufficient(self):
        status, confidence, summary = resolve_status(supporting=0, contradicting=0, confidence=0.0)
        assert status == INSUFFICIENT
        assert confidence == 0.0
        assert "insufficient" in summary.lower()

    def test_confidence_is_bounded(self):
        _, confidence, _ = resolve_status(supporting=1, contradicting=0, confidence=5.0)
        assert confidence <= 0.99


class TestEvidenceCollection:
    def _db(self, rows):
        class _DB:
            async def fetch(self, query, *args):
                return rows
        return _DB()

    def test_supporting_passage_is_returned_with_a_quote(self):
        body = (
            "HNSW index parameters control recall and latency. Setting ef_search higher "
            "improves recall at the cost of speed, and m controls graph connectivity."
        )
        db = self._db([{"id": "n1", "title": "pgvector README", "body": body,
                        "content_type": "fulltext_chunk", "doi": "url:x"}])
        out = asyncio.run(collect_corpus_evidence(db, "HNSW index ef_search recall latency"))
        assert out and out[0]["evidence_source"] == "n1"
        assert len(out[0]["quote"]) >= 60

    def test_one_shared_word_is_not_evidence(self):
        db = self._db([{"id": "n1", "title": "Unrelated", "body": "index of a book about tides and the moon",
                        "content_type": "fulltext_chunk", "doi": None}])
        out = asyncio.run(collect_corpus_evidence(db, "HNSW index ef_search recall latency"))
        assert out == []

    def test_claims_with_few_distinctive_tokens_skip_the_query(self):
        db = self._db([])
        assert asyncio.run(collect_corpus_evidence(db, "it is good")) == []


class TestLedger:
    def test_counts_and_items(self):
        evidence = [{"evidence_source": "a", "polarity": "supports"},
                    {"evidence_source": "b", "polarity": "contradicts"}]
        out = ledger(evidence, MIXED, 0.5)
        assert out["counts"]["supporting"] == 1
        assert out["counts"]["contradicting"] == 1
        assert out["overall_verdict"] == MIXED

    def test_abstained_flag(self):
        out = ledger([], INSUFFICIENT, 0.0)
        assert out["counts"]["abstained"] == 1
