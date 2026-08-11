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

        Scrapes annas-archive.gl/search HTML results page.
        Returns real metadata on success, empty list on failure.
        """
        if not query.strip():
            return []

        logger.debug("Anna's Archive search: %r (limit=%d)", query, limit)

        if self._http is None:
            import httpx
            client = httpx.AsyncClient()
        else:
            client = self._http

        try:
            url = f"https://annas-archive.gl/search?q={query}"
            resp = await client.get(url, timeout=20.0, headers={
                "User-Agent": "Mozilla/5.0 (compatible; Saimon/1.0; research-bot)",
            })
            if resp.status_code != 200:
                logger.warning(
                    "Anna's Archive returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            result_elements = soup.select(".search-result, div[class]")

            results: list[SourceSearchResult] = []
            for el in result_elements[:limit]:
                try:
                    title_el = el.select_one("h3 a, a[href*='/md5/']")
                    title = title_el.get_text(strip=True) if title_el else "Untitled"

                    authors_el = el.select_one(".authors span, [class*='author']")
                    authors = [a.strip() for a in authors_el.get_text(strip=True).split(",")] if authors_el else []

                    year_el = el.select_one(".year, [class*='year']")
                    year_text = year_el.get_text(strip=True) if year_el else ""
                    year = int(year_text) if year_text.isdigit() else None

                    md5_el = el.select_one("[data-md5]")
                    md5 = md5_el.get("data-md5") if md5_el else None

                    file_type_el = el.select_one(".filetype, [class*='file']")
                    file_type = file_type_el.get_text(strip=True).lower() if file_type_el else None

                    results.append(
                        SourceSearchResult(
                            type="academic_paper",
                            identifier=f"md5:{md5}" if md5 else f"aa:{query.replace(' ', '-')}",
                            title=title,
                            authors=authors,
                            year=year,
                            source_index=self.name,
                            source_index_label="Anna's Archive",
                            relevance_score=0.85,
                            file_type=file_type,
                        )
                    )
                except Exception:  # noqa: BLE001 — skip malformed results
                    continue

            return results
        except Exception:
            logger.warning("Anna's Archive search failed", exc_info=True)
            return []
        finally:
            if self._http is None and client is not None:
                await client.aclose()

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Anna's Archive."""
        if not doi.strip():
            return None

        logger.debug("Anna's Archive DOI resolve: %r", doi)

        try:
            results = await self.search(doi, limit=3)
            for result in results:
                if result.doi == doi or doi.lower() in result.title.lower():
                    return result
            # Return first result as best guess
            if results:
                results[0].doi = doi
                results[0].identifier = f"doi:{doi}"
                return results[0]
        except Exception:
            logger.warning("Anna's Archive DOI resolve failed", exc_info=True)
        return None
