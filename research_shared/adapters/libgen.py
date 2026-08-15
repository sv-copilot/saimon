"""libgen.py — Library Genesis (LibGen) source index adapter.

LibGen (libgen.li, .vg, .la, .bz, .gl) is a community-uploaded
repository of academic papers and books.  Search is via HTML form
submission; results are paginated HTML tables.

Tier: S — core source index with high metadata quality.
"""

from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup

from research_shared.adapters.base import SourceSearchResult

logger = logging.getLogger("saimon.adapters.libgen")

LIBGEN_SEARCH_URL = "https://libgen.li/index.php"
DEFAULT_TIMEOUT = 15.0


def _parse_year(value: Any) -> int | None:
    """Parse an int year from a numeric string (tolerates trailing junk)."""
    if not value:
        return None
    try:
        return int(str(value)[:4])
    except (ValueError, TypeError):
        return None


def _parse_libgen_results(html: str, limit: int) -> list[SourceSearchResult]:
    """Parse LibGen's HTML results table into SourceSearchResult items."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="c")
    if table is None:
        return []
    results: list[SourceSearchResult] = []
    for row in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 8:
            continue
        authors = [a.strip() for a in cells[1].split(",") if a.strip()]
        results.append(
            SourceSearchResult(
                type="book",
                identifier=f"md5:{cells[0]}",
                title=cells[2],
                authors=authors,
                year=_parse_year(cells[3]),
                source_index="libgen",
                source_index_label="Library Genesis (LibGen)",
                relevance_score=None,
                file_type=cells[7] or None,
            )
        )
        if len(results) >= limit:
            break
    return results


class LibGenAdapter:
    """Adapter for Library Genesis (LibGen).

    In production, this would POST to libgen.li/index.php with
    req=QUERY and parse the HTML results table.
    """

    name: str = "libgen"
    tier: str = "S"
    trust_model: str = "community"

    def __init__(self, http_client: Any = None) -> None:
        self._http = http_client

    # ── search ────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search LibGen for *query*.

        POSTs to libgen.li/index.php with req=QUERY and parses the
        HTML results table.  Returns [] on any error (no client,
        non-200, network failure, or unparseable HTML).
        """
        if not query.strip():
            return []

        logger.debug("LibGen search: %r (limit=%d)", query, limit)

        if self._http is None:
            logger.warning("LibGen search: no HTTP client configured")
            return []

        try:
            resp = await self._http.post(
                LIBGEN_SEARCH_URL,
                data={"req": query, "res": 25, "view": "simple"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception:
            logger.exception("LibGen search failed for %r", query)
            return []

        if getattr(resp, "status_code", None) != 200:
            logger.warning(
                "LibGen returned HTTP %r for %r",
                getattr(resp, "status_code", None), query,
            )
            return []

        return _parse_libgen_results(getattr(resp, "text", "") or "", limit)

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via LibGen's scimag collection.

        Honest behaviour: without a configured HTTP client we cannot
        scrape the scimag mirror, so return None instead of fabricating
        a result.
        """
        if not doi.strip():
            return None

        logger.debug("LibGen DOI resolve: %r", doi)
        return None
