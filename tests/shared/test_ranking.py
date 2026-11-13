"""Tests for shadow-library relevance ranking (SAIMON-SEARCH-RELIABILITY-1, #201).

The bug: aggregated shadow-search results were title-match noise (VOA news
broadcasts, CIA Reading Room docs, GitHub repo dumps) that the LLM couldn't
verify against, so claims *with* sources still landed inconclusive.

The fix: prefer book sources (Anna's Archive, LibGen, Sci-Hub) over web-ish
Internet Archive hits and down-rank obvious non-book noise.
"""

from __future__ import annotations

from research_shared.adapters.base import SourceSearchResult
from research_shared.adapters.ranking import (
    is_noise_title,
    rank_shadow_results,
    source_priority,
)

_DOCUMENT_INDEXES = {"internet_archive"}


def _result(
    source_index: str, title: str, score: float | None = None
) -> SourceSearchResult:
    return SourceSearchResult(
        type="book" if source_index in _DOCUMENT_INDEXES else "web",
        identifier=f"{source_index}:{title}",
        title=title,
        source_index=source_index,
        source_index_label=source_index,
        relevance_score=score,
    )


class TestRelevancePrefersBooks:
    def test_book_sources_rank_above_internet_archive(self) -> None:
        ia = _result("web_index", "Some web document")
        book = _result("internet_archive", "Deep Learning")
        ranked = rank_shadow_results([ia, book])
        assert ranked[0].source_index == "internet_archive"
        assert ranked[1].source_index == "web_index"

    def test_noise_titles_downranked(self) -> None:
        noise = _result("web_index", "VOA News broadcast archive")
        book = _result("internet_archive", "Attention Is All You Need")
        ranked = rank_shadow_results([noise, book])
        assert ranked[0].source_index == "internet_archive"
        assert ranked[-1].source_index == "web_index"

    def test_relevance_score_breaks_ties_within_priority(self) -> None:
        high = _result("internet_archive", "High scoring book", score=0.9)
        low = _result("internet_archive", "Low scoring book", score=0.1)
        ranked = rank_shadow_results([low, high])
        assert ranked[0].title == "High scoring book"
        assert ranked[1].title == "Low scoring book"

    def test_noise_detection_patterns(self) -> None:
        assert is_noise_title("CIA Reading Room document")
        assert is_noise_title("GitHub repository dump")
        assert is_noise_title("BBC News broadcast")
        assert not is_noise_title("Attention Is All You Need")

    def test_source_priority_books_beat_web(self) -> None:
        assert source_priority(_result("internet_archive", "Book")) > source_priority(
            _result("web_index", "Web")
        )
