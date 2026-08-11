"""annas_archive.py — Anna's Archive source index adapter.

Anna's Archive (annas-archive.gl) is a metasearch engine aggregating
LibGen, Sci-Hub, Z-Library, and Internet Archive.  It provides HTML
search that can be scraped, and periodic database dumps that can be
imported for offline search.

Tier: S — core source index with high metadata quality.
"""

from __future__ import annotations

import logging
from typing import Any

from research_shared.adapters.base import SourceSearchResult

logger = logging.getLogger("saimon.adapters.annas_archive")


class AnnasArchiveAdapter:
    """Adapter for Anna's Archive metasearch.

    In production, this would scrape the HTML search results page at
    `annas-archive.gl/search?q=QUERY` or query imported database dumps.
    """

    name: str = "annas_archive"
    tier: str = "S"
    trust_model: str = "algorithmic"

    def __init__(self, http_client: Any = None) -> None:
        self._http = http_client

    # ── search ────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search Anna's Archive for *query*.

        Currently returns placeholder results.  Production implementation
        would either scrape the HTML search page or query an imported
        database dump.
        """
        if not query.strip():
            return []

        # Placeholder — would scrape annas-archive.gl/search?q=...
        # and parse the HTML results table.
        _ = (self._http, offset)  # reserved for future use
        logger.debug("Anna's Archive search: %r (limit=%d)", query, limit)

        results: list[SourceSearchResult] = []
        for i in range(min(limit, 5)):
            results.append(
                SourceSearchResult(
                    type="academic_paper",
                    identifier=f"md5:aa-placeholder-{i}",
                    title=f"Anna's Archive result {i + 1} for: {query}",
                    authors=[f"Author {chr(65 + i)}"],
                    year=2020 + i,
                    source_index=self.name,
                    source_index_label="Anna's Archive",
                    relevance_score=round(0.95 - i * 0.1, 2),
                    file_type="pdf",
                )
            )
        return results

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Anna's Archive.

        Anna's Archive indexes Sci-Hub/SciDB DOIs, so this would
        check against the SciDB subset.
        """
        if not doi.strip():
            return None

        _ = self._http  # reserved
        logger.debug("Anna's Archive DOI resolve: %r", doi)

        # Placeholder
        return SourceSearchResult(
            type="academic_paper",
            identifier=f"doi:{doi}",
            doi=doi,
            title=f"Paper for DOI: {doi}",
            authors=["Author, A."],
            source_index=self.name,
            source_index_label="Anna's Archive",
            relevance_score=0.95,
            full_text_available=True,
            file_type="pdf",
        )
