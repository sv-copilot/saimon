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
        """
        if not query.strip():
            return []

        logger.debug("Academic Torrents search: %r (limit=%d)", query, limit)

        if self._http is None:
            import httpx
            client = httpx.AsyncClient()
        else:
            client = self._http

        try:
            url = (
                "https://academictorrents.com/apiv2/search"
                f"?q={query}&field=title&field=description"
            )
            resp = await client.get(url, timeout=15.0)
            if resp.status_code != 200:
                logger.warning(
                    "Academic Torrents returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                return []

            data = resp.json()
            if not isinstance(data, list):
                return []

            results: list[SourceSearchResult] = []
            for item in data[:limit]:
                try:
                    results.append(
                        SourceSearchResult(
                            type="dataset",
                            identifier=f"at:{item.get('id', item.get('info_hash', 'unknown'))}",
                            doi=item.get("doi"),
                            title=item.get("title", "Untitled"),
                            authors=item.get("authors", []) if isinstance(item.get("authors"), list) else [item["authors"]] if item.get("authors") else [],
                            year=int(item["year"]) if item.get("year") and str(item["year"]).isdigit() else None,
                            abstract_snippet=item.get("description")[:500] if item.get("description") else None,
                            source_index=self.name,
                            source_index_label="Academic Torrents",
                            relevance_score=0.70,
                            full_text_available=True,
                            file_type="torrent",
                            download_url=item.get("magnet_link"),
                        )
                    )
                except Exception:  # noqa: BLE001 — skip malformed results
                    continue
            return results
        except Exception:
            logger.warning("Academic Torrents search failed", exc_info=True)
            return []
        finally:
            if self._http is None and client is not None:
                await client.aclose()

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Academic Torrents."""
        if not doi.strip():
            return None

        logger.debug("Academic Torrents DOI resolve: %r", doi)

        try:
            results = await self.search(f"doi:{doi}", limit=1)
            if results:
                result = results[0]
                result.doi = doi
                result.identifier = f"doi:{doi}"
                return result
        except Exception:
            logger.warning("Academic Torrents DOI resolve failed", exc_info=True)
        return None
