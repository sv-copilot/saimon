"""test_source_discovery.py — fixture tests for Tier A source discovery.

Tests DOI/URL/arXiv extraction, deduplication, empty-input handling,
max_results truncation, and doi.org URL resolution.
"""

import pytest
from research_shared.source_discovery import (
    SourceDiscoveryCandidate,
    _DOI_PATTERN,
    _URL_PATTERN,
    _ARXIV_COLON_PATTERN,
    _normalize_doi,
    _normalize_url_key,
    _strip_trailing_punct,
    extract_reference_candidates,
)


# ── Regex pattern tests ──────────────────────────────────────────────

class TestDOIRegex:
    def test_simple_doi(self):
        matches = _DOI_PATTERN.findall("See 10.1038/nature12373 for details")
        assert len(matches) >= 1
        assert "10.1038/nature12373" in matches[0]

    def test_doi_with_punctuation(self):
        matches = _DOI_PATTERN.findall("(10.1234/example.1).")
        assert len(matches) >= 1

    def test_doi_in_sentence(self):
        matches = _DOI_PATTERN.findall("The paper 10.1000/journal.2024 was cited")
        assert len(matches) >= 1
        assert "10.1000/journal.2024" in matches[0]

    def test_no_doi(self):
        matches = _DOI_PATTERN.findall("No DOI here, just plain text.")
        assert matches == []


class TestArxivRegex:
    def test_arxiv_colon(self):
        matches = _ARXIV_COLON_PATTERN.findall("arXiv:2301.12345 demonstrates")
        assert len(matches) >= 1
        assert "2301.12345" in matches[0]

    def test_arxiv_with_version(self):
        matches = _ARXIV_COLON_PATTERN.findall("See arXiv:1706.03762v2 for reference")
        assert len(matches) >= 1
        assert "1706.03762v2" in matches[0]

    def test_no_arxiv(self):
        matches = _ARXIV_COLON_PATTERN.findall("No arxiv reference here.")
        assert matches == []


class TestURLRegex:
    def test_simple_url(self):
        matches = _URL_PATTERN.findall("Visit https://example.com/paper.pdf for more")
        assert len(matches) >= 1
        assert "https://example.com/paper.pdf" in matches[0]

    def test_no_url(self):
        matches = _URL_PATTERN.findall("No URL in this text.")
        assert matches == []


# ── Normalization tests ─────────────────────────────────────────────

class TestNormalization:
    def test_normalize_doi_lowercase(self):
        assert _normalize_doi("10.1234/AbCd") == "10.1234/abcd"

    def test_normalize_doi_strips_trailing_punct(self):
        result = _normalize_doi("10.1234/paper.")
        assert not result.endswith(".")

    def test_normalize_url_key(self):
        result = _normalize_url_key("https://Example.COM/path/")
        assert result == "https://example.com/path"

    def test_strip_trailing_punct(self):
        assert _strip_trailing_punct("hello.") == "hello"
        assert _strip_trailing_punct("hello,;)'\"") == "hello"
        assert _strip_trailing_punct("nochange") == "nochange"


# ── extract_reference_candidates tests ───────────────────────────────

class TestExtractDOI:
    def test_single_doi(self):
        candidates = extract_reference_candidates(
            "See 10.1038/nature12373 for details"
        )
        assert len(candidates) >= 1
        assert candidates[0].kind == "doi"
        assert "10.1038/nature12373" in candidates[0].doi

    def test_multiple_dois(self):
        candidates = extract_reference_candidates(
            "Papers: 10.1000/abc.1, 10.1000/xyz.2, and 10.1000/def.3"
        )
        dois = [c.doi for c in candidates if c.kind == "doi"]
        assert len(dois) >= 3


class TestExtractArxiv:
    def test_single_arxiv(self):
        candidates = extract_reference_candidates(
            "arXiv:2301.12345 demonstrates"
        )
        assert any(c.kind == "arxiv" for c in candidates)

    def test_arxiv_url_recognized_as_arxiv(self):
        """arxiv.org/abs/ URLs should be classified as arxiv, not url."""
        candidates = extract_reference_candidates(
            "See https://arxiv.org/abs/1706.03762 for the paper"
        )
        arxiv_cands = [c for c in candidates if c.kind == "arxiv"]
        assert len(arxiv_cands) >= 1


class TestExtractURL:
    def test_url_extraction(self):
        candidates = extract_reference_candidates(
            "More at https://example.com/paper.pdf"
        )
        assert any(c.kind == "url" for c in candidates)


class TestDeduplication:
    def test_duplicate_doi(self):
        candidates = extract_reference_candidates(
            "10.1038/nature12373 and also 10.1038/nature12373 again"
        )
        dois = [c.doi for c in candidates if c.kind == "doi"]
        assert len(dois) == 1  # deduplicated

    def test_duplicate_arxiv(self):
        candidates = extract_reference_candidates(
            "arXiv:2301.12345 and arXiv:2301.12345"
        )
        arxiv_cands = [c for c in candidates if c.kind == "arxiv"]
        assert len(arxiv_cands) == 1

    def test_case_insensitive_doi_dedup(self):
        candidates = extract_reference_candidates(
            "10.1234/AbCd and 10.1234/abcd"
        )
        dois = [c.doi for c in candidates if c.kind == "doi"]
        assert len(dois) == 1


class TestEmptyInput:
    def test_empty_string(self):
        assert extract_reference_candidates("") == []

    def test_no_references(self):
        assert extract_reference_candidates("No references here.") == []

    def test_whitespace_only(self):
        assert extract_reference_candidates("   \n  \t  ") == []


class TestMaxResults:
    def test_max_results_truncation(self):
        text = " ".join([f"10.1234/paper.{i}" for i in range(10)])
        result = extract_reference_candidates(text, max_results=5)
        assert len(result) <= 5

    def test_default_max_results(self):
        text = " ".join([f"10.1234/paper.{i}" for i in range(15)])
        result = extract_reference_candidates(text)
        assert len(result) <= 10  # default max_results


class TestCandidateStructure:
    def test_doi_candidate_has_url(self):
        candidates = extract_reference_candidates("10.1038/nature12373")
        assert candidates[0].url is not None
        assert "doi.org" in candidates[0].url

    def test_arxiv_candidate_has_url(self):
        candidates = extract_reference_candidates("arXiv:2301.12345")
        arxiv = [c for c in candidates if c.kind == "arxiv"][0]
        assert arxiv.url is not None
        assert "arxiv.org" in arxiv.url

    def test_candidate_has_label(self):
        candidates = extract_reference_candidates("10.1038/nature12373")
        assert candidates[0].label is not None
        assert len(candidates[0].label) > 0

    def test_candidate_has_start_index(self):
        candidates = extract_reference_candidates("10.1038/nature12373")
        assert candidates[0].start_index >= 0

    def test_document_order_preserved(self):
        candidates = extract_reference_candidates(
            "First: 10.1000/first.1. Second: arXiv:2302.00001. Third: 10.1000/third.3"
        )
        indices = [c.start_index for c in candidates]
        assert indices == sorted(indices)


class TestDOIOrgURL:
    def test_doi_org_url_resolved_as_doi(self):
        """doi.org/... URLs should be classified as doi, not url."""
        candidates = extract_reference_candidates(
            "See https://doi.org/10.1038/nature12373 for the paper"
        )
        doi_cands = [c for c in candidates if c.kind == "doi"]
        assert len(doi_cands) >= 1
        assert "10.1038/nature12373" in doi_cands[0].doi
