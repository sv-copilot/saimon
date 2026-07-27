"""Tests for deduplication engine — merges cross-index results by DOI."""

import pytest

from research_shared.adapters.base import SourceSearchResult
from research_shared.adapters.dedup import deduplicate


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeduplicateByDOI:
    """DOI-based deduplication."""

    def test_same_doi_merges(self):
        """Two results with the same DOI become one."""
        results = [
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/test",
                doi="10.1038/test",
                title="The Paper",
                source_index="annas_archive",
                source_index_label="Anna's Archive",
                relevance_score=0.9,
            ),
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/test",
                doi="10.1038/test",
                title="The Paper",
                source_index="libgen",
                source_index_label="LibGen",
                relevance_score=0.85,
            ),
        ]
        merged = deduplicate(results)
        assert len(merged) == 1
        assert merged[0].source_index in ("annas_archive", "libgen")

    def test_case_insensitive_doi(self):
        """DOI matching is case-insensitive."""
        results = [
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/Test",
                doi="10.1038/Test",
                title="T",
                source_index="annas_archive",
                source_index_label="A",
                relevance_score=0.9,
            ),
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/test",
                doi="10.1038/test",
                title="T",
                source_index="libgen",
                source_index_label="L",
                relevance_score=0.8,
            ),
        ]
        merged = deduplicate(results)
        assert len(merged) == 1

    def test_prefers_abstract_over_no_abstract(self):
        """The result with an abstract wins when deduplicating."""
        results = [
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/a",
                doi="10.1038/a",
                title="Paper A",
                source_index="libgen",
                source_index_label="LibGen",
                abstract_snippet=None,
                relevance_score=0.95,
            ),
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/a",
                doi="10.1038/a",
                title="Paper A",
                source_index="annas_archive",
                source_index_label="Anna's Archive",
                abstract_snippet="An abstract...",
                relevance_score=0.80,
            ),
        ]
        merged = deduplicate(results)
        assert len(merged) == 1
        assert merged[0].abstract_snippet == "An abstract..."
        assert merged[0].source_index == "annas_archive"


class TestDeduplicateByTitleAuthor:
    """Title+author fallback deduplication."""

    def test_same_title_and_author_merges(self):
        """Two results without DOI but same title+author become one."""
        results = [
            SourceSearchResult(
                type="book",
                identifier="md5:abc",
                title="Deep Learning",
                authors=["Goodfellow, I."],
                source_index="libgen",
                source_index_label="LibGen",
                relevance_score=0.9,
            ),
            SourceSearchResult(
                type="book",
                identifier="md5:def",
                title="Deep Learning",
                authors=["Goodfellow, I."],
                source_index="internet_archive",
                source_index_label="Internet Archive",
                relevance_score=0.7,
            ),
        ]
        merged = deduplicate(results)
        assert len(merged) == 1

    def test_same_title_different_author_does_not_merge(self):
        """Same title but different first author — no merge."""
        results = [
            SourceSearchResult(
                type="book",
                identifier="md5:1",
                title="Deep Learning",
                authors=["Goodfellow, I."],
                source_index="libgen",
                source_index_label="LibGen",
                relevance_score=0.9,
            ),
            SourceSearchResult(
                type="book",
                identifier="md5:2",
                title="Deep Learning",
                authors=["Smith, J."],
                source_index="internet_archive",
                source_index_label="Internet Archive",
                relevance_score=0.7,
            ),
        ]
        merged = deduplicate(results)
        assert len(merged) == 2


class TestDeduplicateEdgeCases:
    """Edge case tests."""

    def test_empty_list(self):
        """Empty input returns empty list."""
        assert deduplicate([]) == []

    def test_single_result(self):
        """Single result returns unchanged."""
        r = SourceSearchResult(
            type="book",
            identifier="md5:x",
            title="Solo",
            source_index="libgen",
            source_index_label="LibGen",
            relevance_score=0.5,
        )
        merged = deduplicate([r])
        assert len(merged) == 1
        assert merged[0] is r

    def test_no_duplicates(self):
        """Distinct results all kept."""
        results = [
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/a",
                doi="10.1038/a",
                title="Paper A",
                source_index="annas_archive",
                source_index_label="A",
                relevance_score=0.9,
            ),
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/b",
                doi="10.1038/b",
                title="Paper B",
                source_index="annas_archive",
                source_index_label="A",
                relevance_score=0.8,
            ),
        ]
        merged = deduplicate(results)
        assert len(merged) == 2

    def test_sorted_by_relevance_desc(self):
        """Results are sorted by relevance_score descending."""
        results = [
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/low",
                doi="10.1038/low",
                title="Low",
                source_index="a",
                source_index_label="A",
                relevance_score=0.1,
            ),
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/high",
                doi="10.1038/high",
                title="High",
                source_index="a",
                source_index_label="A",
                relevance_score=0.99,
            ),
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/mid",
                doi="10.1038/mid",
                title="Mid",
                source_index="a",
                source_index_label="A",
                relevance_score=0.5,
            ),
        ]
        merged = deduplicate(results)
        scores = [r.relevance_score for r in merged]
        assert scores == [0.99, 0.5, 0.1]
