"""ranking.py — relevance ranking for aggregated source results.

Results arrive from sources of different character. An index of whole works
returns something a reader can check the claim against; a broad web-ish index
returns title-match noise (news items, archive dumps, repository pages) that a
citation cannot be verified against. Ranking is therefore a function of what a
result *is*, plus a policy saying which of this deployment's sources it trusts
most.

The policy is declared at the composition point (`research_shared.sources`) and
never here: shared code carries no source names, so a deployment changes its
weighting by changing its own composition, not this module.

SAIMON-SEARCH-RELIABILITY-1 (#201) is the reason the noise down-rank exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from research_shared.adapters.base import SourceSearchResult

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
    """Return True if *title* looks like non-work web noise (news/CIA/GitHub)."""
    if not title:
        return False
    return any(pattern.search(title) for pattern in _NOISE_PATTERNS)


@dataclass(frozen=True)
class RankingPolicy:
    """Which of a deployment's sources it trusts most, and by how much.

    ``preferred_sources`` rank above ``default_priority`` sources, which rank
    above ``deprioritised_sources``. A deployment that trusts nothing in
    particular leaves both sets empty and every source ranks equally.
    """

    preferred_sources: frozenset[str] = field(default_factory=frozenset)
    deprioritised_sources: frozenset[str] = field(default_factory=frozenset)
    preferred_priority: int = 3
    default_priority: int = 2
    deprioritised_priority: int = 1


#: Used when a caller supplies no policy and the composition point declares none.
NEUTRAL_POLICY = RankingPolicy()


def _composition_policy() -> RankingPolicy:
    """The policy this deployment declares, or the neutral one.

    Imported lazily: the composition module imports adapters, which import this
    module's types.
    """
    try:
        from research_shared.sources import ranking_policy
    except ImportError:  # pragma: no cover - composition module always present
        return NEUTRAL_POLICY
    return ranking_policy()


def source_priority(result: SourceSearchResult, policy: RankingPolicy | None = None) -> int:
    """Return a trust priority for *result* (higher = preferred)."""
    active = policy if policy is not None else _composition_policy()
    if result.source_index in active.preferred_sources:
        return active.preferred_priority
    if result.source_index in active.deprioritised_sources:
        return active.deprioritised_priority
    return active.default_priority


def rank_results(
    results: list[SourceSearchResult],
    policy: RankingPolicy | None = None,
) -> list[SourceSearchResult]:
    """Rank aggregated results: preferred sources first, web noise last.

    Ordering key (ascending):
      1. noise flag (0 = clean, 1 = noise)
      2. negative source priority (preferred sources first)
      3. negative relevance score (higher relevance first)
      4. title (deterministic tiebreak)
    """

    def sort_key(r: SourceSearchResult):
        return (
            1 if is_noise_title(r.title) else 0,
            -source_priority(r, policy),
            -(r.relevance_score if r.relevance_score is not None else 0.0),
            r.title.lower(),
        )

    return sorted(results, key=sort_key)
