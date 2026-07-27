"""academic_torrents.py — Academic Torrents source index adapter.

Academic Torrents (academictorrents.com) provides a REST API for
searching dataset and paper torrents.  It's particularly useful
for large datasets and paper collections.

Tier: A — strong source index with a clean REST API.
"""

from __future__ import annotations

import logging
from typing import Any

from research_shared.adapters.base import SourceSearchResult

logger = logging.getLogger("saimon.adapters.academic_torrents")


class AcademicTorrentsAdapter:
    """Adapter for Academic Torrents (academictorrents.com).

    REST API at academictorrents.com/apiv2/ returns JSON.
    Search: GET /apiv2/search?q=QUERY&field=title&field=description
    """

    name: str = "academic_torrents"
    tier: str = "A"
    trust_model: str = "community"

    def __init__(self, http_client: Any = None) -> None:
        self._http = http_client

    # ── search ────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search Academic Torrents for *query*.

        Uses academictorrents.com/apiv2/search REST endpoint.

        Currently returns placeholder results.  Production would call::

            GET /apiv2/search?q={query}&field=title&field=description
        """
        if not query.strip():
            return []

        _ = (self._http, offset)  # reserved
        logger.debug("Academic Torrents search: %r (limit=%d)", query, limit)

        results: list[SourceSearchResult] = []
        for i in range(min(limit, 5)):
            results.append(
                SourceSearchResult(
                    type="dataset",
                    identifier=f"at:{query.replace(' ', '-')}-{i}",
                    title=f"Academic Torrents result {i + 1} for: {query}",
                    authors=[f"Researcher {chr(65 + i)}"],
                    year=2020 + i,
                    source_index=self.name,
                    source_index_label="Academic Torrents",
                    relevance_score=round(0.82 - i * 0.1, 2),
                    full_text_available=True,
                    file_type="torrent",
                )
            )
        return results

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Academic Torrents.

        Academic Torrents indexes DOIs for some paper collections.
        """
        if not doi.strip():
            return None

        _ = self._http  # reserved
        logger.debug("Academic Torrents DOI resolve: %r", doi)

        return SourceSearchResult(
            type="academic_paper",
            identifier=f"doi:{doi}",
            doi=doi,
            title=f"AT paper for DOI: {doi}",
            authors=["Unknown"],
            source_index=self.name,
            source_index_label="Academic Torrents",
            relevance_score=0.70,
            full_text_available=True,
            file_type="torrent",
        )
