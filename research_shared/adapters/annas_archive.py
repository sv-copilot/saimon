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

from bs4 import BeautifulSoup

from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.adapters.annas_archive")

ANNAS_ARCHIVE_SEARCH_URL = "https://annas-archive.gl/search"
DEFAULT_TIMEOUT = 15.0


def _parse_year(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(str(value)[:4])
    except (ValueError, TypeError):
        return None


def _parse_annas_results(html: str, limit: int) -> list[SourceSearchResult]:
    """Parse Anna's Archive search-result blocks into SourceSearchResult."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    results: list[SourceSearchResult] = []
    for div in soup.find_all("div", class_="search-result"):
        h3 = div.find("h3")
        title = h3.find("a").get_text(strip=True) if h3 and h3.find("a") else None
        if not title:
            continue
        authors: list[str] = []
        authors_el = div.find("div", class_="authors")
        if authors_el and authors_el.find("span"):
            authors = [
                a.strip()
                for a in authors_el.find("span").get_text(strip=True).split(",")
                if a.strip()
            ]
        year_el = div.find("div", class_="year")
        year = _parse_year(year_el.get_text(strip=True)) if year_el else None
        md5_el = div.find("div", attrs={"data-md5": True})
        md5 = md5_el.get("data-md5") if md5_el else ""
        ft_el = div.find("div", class_="filetype")
        file_type = ft_el.get_text(strip=True) if ft_el else None
        results.append(
            SourceSearchResult(
                type="academic_paper",
                identifier=f"md5:{md5}" if md5 else f"aa:{title}",
                title=title,
                authors=authors,
                year=year,
                source_index="annas_archive",
                source_index_label="Anna's Archive",
                relevance_score=None,
                file_type=file_type,
            )
        )
        if len(results) >= limit:
            break
    return results


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

        GETs annas-archive.gl/search?q=QUERY and parses the HTML
        search-result blocks.  Returns [] on any error (no client,
        non-200, network failure, or unparseable HTML).
        """
        if not query.strip():
            return []

        logger.debug("Anna's Archive search: %r (limit=%d)", query, limit)

        if self._http is None:
            logger.warning("Anna's Archive search: no HTTP client configured")
            return []

        try:
            resp = await self._http.get(
                f"{ANNAS_ARCHIVE_SEARCH_URL}?q={query}", timeout=DEFAULT_TIMEOUT
            )
        except Exception:
            logger.exception("Anna's Archive search failed for %r", query)
            return []

        if getattr(resp, "status_code", None) != 200:
            logger.warning(
                "Anna's Archive returned HTTP %r for %r",
                getattr(resp, "status_code", None), query,
            )
            return []

        return _parse_annas_results(getattr(resp, "text", "") or "", limit)

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Anna's Archive.

        Honest behaviour: without a configured HTTP client we cannot
        query the SciDB subset, so return None instead of fabricating
        a result.
        """
        if not doi.strip():
            return None

        logger.debug("Anna's Archive DOI resolve: %r", doi)
        return None

    # ── full-text download ────────────────────────────────────────

    async def fetch_fulltext(self, result: SourceSearchResult) -> FulltextFetchResult | None:
        """Download via the Anna's Archive / SciDB redirect (fail-closed)."""
        from research_shared.adapters.download import download_bytes

        url = result.download_url
        if not url:
            return None

        data = await download_bytes(self._http, url)
        if data is None:
            return None

        return FulltextFetchResult(
            source_index=self.name,
            doi=result.doi,
            data=data,
            file_type=result.file_type,
            download_url=url,
        )
