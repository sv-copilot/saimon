"""ranking.py — relevance ranking for aggregated archive results.

SAIMON-SEARCH-RELIABILITY-1 (#201): a public archive returns title-match noise
(news broadcasts, CIA Reading Room docs, GitHub repo dumps) that a verifier
cannot check against. Prefer book and paper results over web-ish hits and
down-rank obvious non-book noise.

Priority is derived from the result *type*, not from the source's name: the
ranking should not need editing every time an index is added or removed.
"""

from __future__ import annotations

import re

from research_shared.adapters.base import SourceSearchResult

# Result types that represent citable documents rather than web pages.
_DOCUMENT_TYPES = frozenset({"book", "paper", "article"})

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
    """Return a document-vs-web priority for a source result (higher = preferred)."""
    if getattr(result, "type", None) in _DOCUMENT_TYPES:
        return 3
    if getattr(result, "type", None) in ("web", "web_page"):
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
