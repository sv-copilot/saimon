"""dedup.py — cross-index deduplication engine.

When the same work appears in more than one source index, the dedup engine
merges the records into a single canonical result using DOI as the primary key,
falling back to title plus first-author normalization.
"""

from __future__ import annotations

from research_shared.adapters.base import SourceSearchResult


def deduplicate(
    results: list[SourceSearchResult],
) -> list[SourceSearchResult]:
    """Deduplicate results by DOI, falling back to title+first-author.

    For each duplicate group, picks the best result (preferring those
    with abstracts and full-text availability) and drops the rest.
    Results are returned sorted by relevance_score descending.

    Args:
        results: Raw search results potentially containing duplicates.

    Returns:
        Deduplicated and relevance-sorted list of results.
    """
    if not results:
        return []

    doi_groups: dict[str, list[SourceSearchResult]] = {}
    title_groups: dict[str, list[SourceSearchResult]] = {}
    no_key: list[SourceSearchResult] = []

    for r in results:
        if r.doi:
            key = r.doi.strip().lower()
            doi_groups.setdefault(key, []).append(r)
        elif r.title:
            title_key = " ".join(r.title.lower().split())
            if r.authors:
                surname = r.authors[0].split(",")[0].strip().lower()
                title_key = f"{title_key}||{surname}"
            title_groups.setdefault(title_key, []).append(r)
        else:
            no_key.append(r)

    merged: list[SourceSearchResult] = []

    for group in list(doi_groups.values()) + list(title_groups.values()):
        if len(group) == 1:
            merged.append(group[0])
            continue

        # Pick best: prefer abstract > full_text > highest relevance
        best = max(
            group,
            key=lambda r: (
                1 if r.abstract_snippet else 0,
                1 if r.full_text_available else 0,
                r.relevance_score or 0.0,
            ),
        )
        merged.append(best)

    merged.extend(no_key)
    merged.sort(key=lambda r: r.relevance_score or 0.0, reverse=True)
    return merged
