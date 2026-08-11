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
        """
        if not query.strip():
            return []

        logger.debug("Internet Archive search: %r (limit=%d)", query, limit)

        if self._http is None:
            import httpx
            client = httpx.AsyncClient()
        else:
            client = self._http

        try:
            page = max(offset // limit + 1, 1)
            url = (
                "https://archive.org/advancedsearch.php"
                f"?q={query}&rows={limit}&page={page}&output=json"
            )
            resp = await client.get(url, timeout=15.0)
            if resp.status_code != 200:
                logger.warning(
                    "Internet Archive returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                return []

            data = resp.json()
            docs = data.get("response", {}).get("docs", [])
            results: list[SourceSearchResult] = []
            for doc in docs[:limit]:
                try:
                    results.append(
                        SourceSearchResult(
                            type="book" if doc.get("mediatype") == "texts" else "academic_paper",
                            identifier=f"ia:{doc.get('identifier', 'unknown')}",
                            doi=doc.get("doi"),
                            title=doc.get("title", "Untitled"),
                            authors=doc.get("creator", []) if isinstance(doc.get("creator"), list) else [doc["creator"]] if doc.get("creator") else [],
                            year=int(doc["year"]) if doc.get("year") and str(doc["year"]).isdigit() else None,
                            abstract_snippet=doc.get("description")[:500] if doc.get("description") else None,
                            source_index=self.name,
                            source_index_label="Internet Archive",
                            relevance_score=0.75,
                            full_text_available=True,
                            file_type="pdf",
                        )
                    )
                except Exception:  # noqa: BLE001 — skip malformed results
                    continue
            return results
        except Exception:
            logger.warning("Internet Archive search failed", exc_info=True)
            return []
        finally:
            if self._http is None and client is not None:
                await client.aclose()

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Internet Archive."""
        if not doi.strip():
            return None

        logger.debug("Internet Archive DOI resolve: %r", doi)

        try:
            results = await self.search(f"doi:{doi}", limit=1)
            if results:
                result = results[0]
                result.doi = doi
                result.identifier = f"doi:{doi}"
                return result
        except Exception:
            logger.warning("Internet Archive DOI resolve failed", exc_info=True)
        return None
