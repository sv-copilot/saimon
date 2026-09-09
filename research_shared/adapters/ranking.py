"""ranking.py — relevance ranking for aggregated shadow-library results.

SAIMON-SEARCH-RELIABILITY-1 (#201): Internet Archive returns title-match noise
(news broadcasts, CIA Reading Room docs, GitHub repo dumps) that the LLM
cannot verify against.  Prefer book sources (Anna's Archive, LibGen, Sci-Hub)
over web-ish Internet Archive hits and down-rank obvious non-book noise.
"""

from __future__ import annotations

import re

from research_shared.adapters.base import SourceSearchResult

# Source indexes whose results are books/papers (verifiable), ranked above
# web-ish Internet Archive hits.
_BOOK_SOURCE_INDEXES = frozenset({"annas_archive", "libgen", "scihub"})

_NOISE_PATTERNS = (
    re.compile(r"\bnews\b", re.IGNORECASE),
    re.compile(r"\bnewscast\b", re.IGNORECASE),
    re.compile(r"\bbroadcast\b", re.IGNORECASE),
    re.compile(r"\bcia\b", re.IGNORECASE),
    re.compile(r"\bcentral intelligence agency\b", re.IGNORECASE),
    re.compile(r"\bgithub\b", re.IGNORECASE),
    re.compile(r"\bgit repo(?:sitory)?\b", re.IGNORECASE),
    re.compile(r"\brepo(?:sitory)? dump\b", re.IGNORECASE),
)


def is_noise_title(title: str) -> bool:
    """Return True if *title* looks like non-book web noise (news/CIA/GitHub)."""
    if not title:
        return False
    return any(pattern.search(title) for pattern in _NOISE_PATTERNS)


def source_priority(result: SourceSearchResult) -> int:
    """Return a book-vs-web priority for a source result (higher = preferred)."""
    if result.source_index in _BOOK_SOURCE_INDEXES:
        return 3
    if result.source_index == "internet_archive":
        return 1
    return 2


def rank_shadow_results(
    results: list[SourceSearchResult],
) -> list[SourceSearchResult]:
    """Rank aggregated results: book sources first, web noise last.

    Ordering key (ascending):
      1. noise flag (0 = clean, 1 = noise)
      2. negative source priority (book sources first)
      3. negative relevance score (higher relevance first)
      4. title (deterministic tiebreak)
    """

    def sort_key(r: SourceSearchResult):
        return (
            1 if is_noise_title(r.title) else 0,
            -source_priority(r),
            -(r.relevance_score if r.relevance_score is not None else 0.0),
            r.title.lower(),
        )

    return sorted(results, key=sort_key)
