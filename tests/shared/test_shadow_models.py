"""Tests for SourceSearchResult model — shadow library search result shape."""

import pytest
from pydantic import ValidationError

from research_shared.adapters.base import SourceSearchResult


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestSourceSearchResultValidation:
    """SourceSearchResult model validation tests."""

    def test_valid_minimal_result(self):
        """A result with only required fields validates."""
        result = SourceSearchResult(
            type="academic_paper",
            identifier="doi:10.1038/s41586-023-06004-z",
            title="Attention Is All You Need",
            source_index="annas_archive",
            source_index_label="Anna's Archive",
        )
        assert result.type == "academic_paper"
        assert result.identifier == "doi:10.1038/s41586-023-06004-z"
        assert result.title == "Attention Is All You Need"
        assert result.authors == []
        assert result.year is None
        assert result.doi is None
        assert result.abstract_snippet is None
        assert result.full_text_available is False

    def test_valid_full_result(self):
        """A result with all fields validates."""
        result = SourceSearchResult(
            type="academic_paper",
            identifier="doi:10.1038/s41586-023-06004-z",
            doi="10.1038/s41586-023-06004-z",
            title="Attention Is All You Need",
            authors=["Vaswani, A.", "Shazeer, N.", "Parmar, N."],
            year=2017,
            abstract_snippet="The dominant sequence transduction models...",
            source_index="annas_archive",
            source_index_label="Anna's Archive",
            relevance_score=0.97,
            full_text_available=True,
            file_type="pdf",
            download_url="https://example.com/paper.pdf",
        )
        assert result.year == 2017
        assert len(result.authors) == 3
        assert result.relevance_score == 0.97
        assert result.file_type == "pdf"

    def test_empty_title_rejected(self):
        """An empty title should fail validation."""
        with pytest.raises(ValidationError):
            SourceSearchResult(
                type="academic_paper",
                identifier="doi:10.1038/test",
                title="",
                source_index="annas_archive",
                source_index_label="Anna's Archive",
            )

    def test_relevance_score_out_of_range(self):
        """Relevance score outside 0.0–1.0 should fail."""
        with pytest.raises(ValidationError):
            SourceSearchResult(
                type="book",
                identifier="md5:abc123",
                title="Some Book",
                source_index="libgen",
                source_index_label="LibGen",
                relevance_score=1.5,
            )

    def test_additional_fields_rejected(self):
        """Extra fields should be rejected (extra='forbid')."""
        with pytest.raises(ValidationError):
            SourceSearchResult(
                type="book",
                identifier="md5:abc",
                title="Test",
                source_index="libgen",
                source_index_label="LibGen",
                unknown_field="should fail",
            )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSourceSearchResultSerialization:
    """JSON round-trip tests."""

    def test_round_trip_json(self):
        """Model serializes to JSON and back without losing data."""
        original = SourceSearchResult(
            type="academic_paper",
            identifier="doi:10.1038/s41586-023-06004-z",
            doi="10.1038/s41586-023-06004-z",
            title="Attention Is All You Need",
            authors=["Vaswani, A.", "Shazeer, N."],
            year=2017,
            abstract_snippet="The dominant...",
            source_index="annas_archive",
            source_index_label="Anna's Archive",
            relevance_score=0.97,
            full_text_available=True,
            file_type="pdf",
            download_url="https://example.com/paper.pdf",
        )
        json_str = original.model_dump_json()
        restored = SourceSearchResult.model_validate_json(json_str)
        assert restored == original

    def test_minimal_round_trip_json(self):
        """Minimal result round-trips through JSON."""
        original = SourceSearchResult(
            type="book",
            identifier="md5:def456",
            title="A Book",
            source_index="libgen",
            source_index_label="Library Genesis",
        )
        json_str = original.model_dump_json()
        restored = SourceSearchResult.model_validate_json(json_str)
        assert restored == original


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestSourceSearchResultDefaults:
    """Default value tests."""

    def test_authors_defaults_to_empty_list(self):
        result = SourceSearchResult(
            type="book",
            identifier="md5:1",
            title="T",
            source_index="s",
            source_index_label="S",
        )
        assert result.authors == []

    def test_full_text_available_defaults_false(self):
        result = SourceSearchResult(
            type="book",
            identifier="md5:1",
            title="T",
            source_index="s",
            source_index_label="S",
        )
        assert result.full_text_available is False
