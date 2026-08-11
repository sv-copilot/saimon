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
        """Sci-Hub is NOT a search engine — return empty list.

        Sci-Hub's primary function is DOI resolution, not keyword
        search.  For search, use Anna's Archive or LibGen.
        """
        _ = (query, limit, offset)
        logger.info("Sci-Hub search called — returning empty (not a search engine)")
        return []

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Sci-Hub.

        Checks https://sci-hub.ru/{doi} with a HEAD request.
        Returns a SourceSearchResult if the PDF is available.
        """
        if not doi.strip():
            return None

        logger.debug("Sci-Hub DOI resolve: %r", doi)

        if self._http is None:
            import httpx
            client = httpx.AsyncClient()
        else:
            client = self._http

        try:
            url = f"https://sci-hub.ru/{doi}"
            resp = await client.head(url, timeout=15.0, follow_redirects=True)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                is_pdf = "pdf" in content_type.lower() or "octet-stream" in content_type.lower()
                return SourceSearchResult(
                    type="academic_paper",
                    identifier=f"doi:{doi}",
                    doi=doi,
                    title=f"Paper for DOI: {doi}",
                    authors=[],
                    source_index=self.name,
                    source_index_label="Sci-Hub",
                    relevance_score=0.92,
                    full_text_available=is_pdf,
                    file_type="pdf" if is_pdf else None,
                    download_url=url,
                )
            logger.warning("Sci-Hub DOI resolve returned %d for %s", resp.status_code, doi)
            return None
        except Exception:
            logger.warning("Sci-Hub DOI resolve failed for %s", doi, exc_info=True)
            return None
        finally:
            if self._http is None and client is not None:
                await client.aclose()
