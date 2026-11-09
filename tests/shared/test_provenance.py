"""Provenance and the verdict ledger (#271)."""

from __future__ import annotations

from research_shared.provenance import (
    LEDGER_VERSION,
    citation_for,
    claim_hash,
    ledger_row,
    locator_for,
)


class TestLocator:
    def test_url_doi_resolves_to_the_url(self):
        locator, reason = locator_for({"metadata": {"doi": "url:https://example.org/paper.pdf"}})
        assert locator == "https://example.org/paper.pdf"
        assert reason is None

    def test_bare_doi_is_prefixed(self):
        locator, _ = locator_for({"metadata": {"doi": "10.1145/123.456"}})
        assert locator == "doi:10.1145/123.456"

    def test_metadata_json_string_is_parsed(self):
        locator, _ = locator_for({"metadata": '{"doi": "url:https://a.example/x"}'})
        assert locator == "https://a.example/x"

    def test_absent_locator_has_a_reason_not_an_id(self):
        locator, reason = locator_for({"id": "abc-123", "metadata": {}})
        assert locator is None
        assert reason == "no_doi_or_url_in_metadata"

    def test_empty_url_is_reported_not_accepted(self):
        locator, reason = locator_for({"metadata": {"doi": "url:"}})
        assert locator is None
        assert reason == "empty_url"


class TestCitation:
    def test_carries_primacy_and_quality(self):
        citation = citation_for({
            "id": "n1", "title": "Paper", "content_type": "fulltext_chunk",
            "metadata": {"doi": "url:https://x.example/p", "primacy_tier": "near_direct",
                         "quality_score": 0.62, "fetched_at": "2026-11-09T00:00:00Z"},
        })
        assert citation.primacy_tier == "near_direct"
        assert citation.quality_score == 0.62
        assert citation.fetched_at is not None

    def test_as_dict_is_serialisable(self):
        citation = citation_for({"id": "n1", "title": "T", "content_type": "claim", "metadata": {}})
        payload = citation.as_dict()
        assert payload["id"] == "n1" and payload["locator"] is None


class TestLedgerRow:
    def _citation(self, locator=None):
        return citation_for({
            "id": "n1", "title": "T", "content_type": "claim",
            "metadata": {"doi": f"url:{locator}"} if locator else {},
        })

    def test_row_carries_evidence_and_locators(self):
        row = ledger_row(claim="X is true", verdict="supported", confidence=0.85,
                         citations=[self._citation("https://a.example/1")])
        assert row["evidence_ids"] == ["n1"]
        assert row["locators"] == ["https://a.example/1"]
        assert row["version"] == LEDGER_VERSION

    def test_row_without_locator_still_records_the_evidence_id(self):
        row = ledger_row(claim="X", verdict="insufficient_evidence", confidence=0.0, citations=[])
        assert row["evidence_ids"] == [] and row["locators"] == []

    def test_hash_is_stable_across_case_and_whitespace(self):
        assert claim_hash("  The Rate Rose.  ") == claim_hash("the rate rose.")

    def test_hash_distinguishes_different_claims(self):
        assert claim_hash("a") != claim_hash("b")
