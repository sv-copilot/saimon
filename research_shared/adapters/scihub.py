"""scihub.py — Sci-Hub / SciDB source index adapter.

Sci-Hub is primarily a DOI resolver (not a search engine).  Given a
DOI, it returns the full PDF.  SciDB (accessible via Anna's Archive)
adds a search layer on top of Sci-Hub's corpus.

Tier: S — core source index for DOI-based paper resolution.
"""

from __future__ import annotations

import logging
from typing import Any

from research_shared.adapters.base import SourceSearchResult

logger = logging.getLogger("saimon.adapters.scihub")


class SciHubAdapter:
    """Adapter for Sci-Hub / SciDB.

    Primary use case is DOI resolution.  Search is delegated to
    SciDB via Anna's Archive.
    """

    name: str = "scihub"
    tier: str = "S"
    trust_model: str = "algorithmic"

    def __init__(self, http_client: Any = None) -> None:
        self._http = http_client

    # ── search ────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search SciDB for *query* (delegated to SciDB subset).

        Sci-Hub itself is not a search engine; this searches the
        SciDB index that sits on top of Sci-Hub's corpus.
        """
        if not query.strip():
            return []

        _ = (self._http, offset)  # reserved
        logger.debug("SciDB search: %r (limit=%d)", query, limit)

        results: list[SourceSearchResult] = []
        for i in range(min(limit, 3)):
            results.append(
                SourceSearchResult(
                    type="academic_paper",
                    identifier=f"doi:10.1000/scihub-placeholder-{i}",
                    doi=f"10.1000/scihub-placeholder-{i}",
                    title=f"SciDB result {i + 1} for: {query}",
                    authors=[f"Researcher {chr(65 + i)}"],
                    year=2019 + i,
                    source_index=self.name,
                    source_index_label="Sci-Hub / SciDB",
                    relevance_score=round(0.88 - i * 0.1, 2),
                    full_text_available=True,
                    file_type="pdf",
                )
            )
        return results

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Sci-Hub.

        Sci-Hub is the canonical DOI resolver for paywalled papers.
        Given a DOI, it returns the full PDF.

        In production, this would hit `sci-hub.ru/DOI_HERE` and
        confirm the PDF is available.
        """
        if not doi.strip():
            return None

        _ = self._http  # reserved
        logger.debug("Sci-Hub DOI resolve: %r", doi)

        return SourceSearchResult(
            type="academic_paper",
            identifier=f"doi:{doi}",
            doi=doi,
            title=f"Sci-Hub paper for DOI: {doi}",
            authors=["Unknown"],
            source_index=self.name,
            source_index_label="Sci-Hub / SciDB",
            relevance_score=0.92,
            full_text_available=True,
            file_type="pdf",
            download_url=f"https://sci-hub.ru/{doi}",
        )
