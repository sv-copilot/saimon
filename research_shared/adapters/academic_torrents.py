"""academic_torrents.py — Academic Torrents source index adapter.

Academic Torrents (academictorrents.com) historically provided a REST API
for searching dataset and paper torrents.

Status (SAIMON-ACADEMIC-TORRENTS-404-1): the ``/apiv2/search`` endpoint has
been **removed** from the upstream API.  The ``/apiv2/`` root is still live
and now lists only entry/collection/test routes — there is no query-based
search endpoint.  This adapter is therefore marked ``disabled`` so callers
stop expecting results from a dead source.  ``search()``/``resolve_doi()``
return ``[]``/``None`` immediately (fail-closed) instead of timing out.
"""

from __future__ import annotations

import logging
from typing import Any

from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.adapters.academic_torrents")


class AcademicTorrentsAdapter:
    """Adapter for Academic Torrents (academictorrents.com).

    The query-based search endpoint (``GET /apiv2/search``) was removed from
    the upstream API, so this adapter is disabled and never performs network
    calls.  ``search()`` returns ``[]`` and ``resolve_doi()`` returns ``None``
    immediately (fail-closed).
    """

    name: str = "academic_torrents"
    tier: str = "A"
    trust_model: str = "community"

    # SAIMON-ACADEMIC-TORRENTS-404-1 — the apiv2/search endpoint is gone.
    disabled: bool = True
    disabled_reason: str = (
        "academictorrents.com/apiv2/search was removed from the API; "
        "no query-based search endpoint exists"
    )

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
        if self.disabled:
            logger.debug(
                "Academic Torrents search disabled (%s); returning []",
                self.disabled_reason,
            )
            return []
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
        if self.disabled:
            logger.debug(
                "Academic Torrents DOI resolve disabled (%s); returning None",
                self.disabled_reason,
            )
            return None
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
