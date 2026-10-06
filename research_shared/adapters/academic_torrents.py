"""academic_torrents.py — Academic Torrents source index adapter.

Academic Torrents (academictorrents.com) provides a REST API for
searching dataset and paper torrents.  It's particularly useful
for large datasets and paper collections.

Tier: A — strong source index with a clean REST API.
"""

from __future__ import annotations

import logging
from typing import Any

from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.adapters.academic_torrents")


class AcademicTorrentsAdapter:
    """Adapter for Academic Torrents (academictorrents.com).

    REST API at academictorrents.com/apiv2/ returns JSON.
    Search: GET /apiv2/search?q=QUERY&field=title&field=description
    """

    name: str = "academic_torrents"
    tier: str = "A"
    trust_model: str = "community"
    label: str = "Academic Torrents"
    kind: str = "dataset"
    access: str = "anonymous"

    def __init__(self, http_client: Any = None) -> None:
        self._http = http_client

    # ── search ────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search Academic Torrents for *query*.

        Uses academictorrents.com/apiv2/search REST endpoint::

            GET /apiv2/search?q={query}&field=title&field=description

        Returns up to *limit* results mapped to SourceSearchResult.
        Returns empty list on any error (timeout, non-200, parse failure).
        """
        if not query.strip():
            return []

        logger.debug("Academic Torrents search: %r (limit=%d)", query, limit)

        import asyncio

        import httpx

        client: Any = self._http
        close_client = False

        if client is None:
            client = httpx.AsyncClient(timeout=15.0)
            close_client = True

        try:
            url = "https://academictorrents.com/apiv2/search"
            params: dict = {
                "q": query,
                "field": ["title", "description"],
            }
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            results: list[SourceSearchResult] = []
            for item in data[:limit]:
                # Handle both real API shape (uploader) and test mock (authors)
                authors: list[str] = []
                raw_authors = item.get("authors")
                if raw_authors and isinstance(raw_authors, list):
                    authors = [str(a) for a in raw_authors]
                elif item.get("uploader"):
                    authors = [str(item["uploader"])]

                results.append(
                    SourceSearchResult(
                        type="dataset",
                        identifier=f"at:{item.get('info_hash', item.get('id', ''))}",
                        doi=item.get("doi"),
                        title=item.get("title", "Unknown"),
                        authors=authors,
                        year=self._parse_year(item.get("date_added") or item.get("year")),
                        abstract_snippet=(item.get("description", "") or "")[:500],
                        source_index=self.name,
                        source_index_label="Academic Torrents",
                        relevance_score=None,
                        full_text_available=True,
                        file_type=item.get("file_type"),
                        download_url=item.get("magnet_link") or item.get("download_url"),
                    )
                )
            return results
        except Exception:
            logger.exception("Academic Torrents search failed for %r", query)
            return []
        finally:
            if close_client:
                await client.aclose()

            # Rate-limit: 1-second sleep between requests
            await asyncio.sleep(1.0)

    @staticmethod
    def _parse_year(date_str: Any) -> int | None:
        """Parse year from a date string like '2023-01-15' or '2023'."""
        if not date_str:
            return None
        try:
            return int(str(date_str)[:4])
        except (ValueError, TypeError):
            return None

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Academic Torrents.

        Academic Torrents indexes DOIs for some paper collections.
        Searches by DOI and returns the first match, or None.
        """
        if not doi.strip():
            return None

        logger.debug("Academic Torrents DOI resolve: %r", doi)

        import httpx

        client: Any = self._http
        close_client = False

        if client is None:
            client = httpx.AsyncClient(timeout=15.0)
            close_client = True

        try:
            url = "https://academictorrents.com/apiv2/search"
            params: dict = {
                "q": doi,
                "field": ["title", "description"],
            }
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return None

            item = data[0]
            return SourceSearchResult(
                type="academic_paper",
                identifier=f"doi:{doi}",
                doi=doi,
                title=item.get("title", f"AT paper for DOI: {doi}"),
                authors=[item.get("uploader", "")] if item.get("uploader") else ["Unknown"],
                year=self._parse_year(item.get("date_added")),
                abstract_snippet=(item.get("description", "") or "")[:500],
                source_index=self.name,
                source_index_label="Academic Torrents",
                relevance_score=None,
                full_text_available=True,
                file_type=item.get("file_type"),
                download_url=item.get("magnet_link"),
            )
        except Exception:
            logger.exception("Academic Torrents DOI resolve failed for %r", doi)
            return None
        finally:
            if close_client:
                await client.aclose()

    # ── full-text download ────────────────────────────────────────

    async def fetch_fulltext(self, result: SourceSearchResult) -> FulltextFetchResult | None:
        """Surface the magnet link only — no auto-download of torrents.

        Returns a result with ``data=None`` and the magnet ``download_url``.
        """
        magnet = result.download_url
        if not magnet:
            return None
        return FulltextFetchResult(
            source_index=self.name,
            doi=result.doi,
            data=None,
            file_type="torrent",
            download_url=magnet,
        )
