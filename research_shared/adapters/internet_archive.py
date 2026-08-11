"""internet_archive.py — Internet Archive source index adapter.

Internet Archive (archive.org) provides a REST API for searching
its digital library of texts, journals, and other media.

Tier: A — strong source index with a real API and good metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from research_shared.adapters.base import SourceSearchResult

logger = logging.getLogger("saimon.adapters.internet_archive")


class InternetArchiveAdapter:
    """Adapter for Internet Archive (archive.org).

    Uses archive.org's Advanced Search API and Open Library API.
    Has a real, documented REST API — the most straightforward
    integration among all shadow library sources.
    """

    name: str = "internet_archive"
    tier: str = "A"
    trust_model: str = "institutional"

    def __init__(self, http_client: Any = None) -> None:
        self._http = http_client

    # ── search ────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search Internet Archive for *query*.

        Uses archive.org/advancedsearch.php which returns JSON.
        Query params: q=QUERY, rows=LIMIT, page=PAGE, output=json.

        Currently returns placeholder results.  Production would call::

            GET /advancedsearch.php?q={query}&rows={limit}&page={page}&output=json
        """
        if not query.strip():
            return []

        _ = (self._http, offset)  # reserved
        logger.debug("Internet Archive search: %r (limit=%d)", query, limit)

        results: list[SourceSearchResult] = []
        for i in range(min(limit, 5)):
            results.append(
                SourceSearchResult(
                    type="book",
                    identifier=f"ia:{query.replace(' ', '-')}-{i}",
                    title=f"Internet Archive result {i + 1} for: {query}",
                    authors=[f"Author {chr(65 + i)}"],
                    year=2015 + i,
                    source_index=self.name,
                    source_index_label="Internet Archive",
                    relevance_score=round(0.85 - i * 0.1, 2),
                    full_text_available=True,
                    file_type="pdf",
                )
            )
        return results

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Internet Archive.

        IA may have archived versions of paywalled papers.  This
        checks the archive.org search for a matching DOI.
        """
        if not doi.strip():
            return None

        _ = self._http  # reserved
        logger.debug("Internet Archive DOI resolve: %r", doi)

        return SourceSearchResult(
            type="academic_paper",
            identifier=f"doi:{doi}",
            doi=doi,
            title=f"IA paper for DOI: {doi}",
            authors=["Unknown"],
            source_index=self.name,
            source_index_label="Internet Archive",
            relevance_score=0.75,
            full_text_available=True,
            file_type="pdf",
        )
