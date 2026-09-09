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

from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.adapters.libgen")

LIBGEN_SEARCH_URL = "https://libgen.li/index.php"
LIBGEN_DOWNLOAD_URL = "https://libgen.li/ads.php"
DEFAULT_TIMEOUT = 15.0


def _parse_year(value: Any) -> int | None:
    """Parse an int year from a numeric string (tolerates trailing junk)."""
    if not value:
        return None
    try:
        return int(str(value)[:4])
    except (ValueError, TypeError):
        return None


def _split_author_names(text: str) -> list[str]:
    """Split an author list on ``;`` (LibGen/AA style) or ``,`` (legacy)."""
    if ";" in text:
        return [part.strip() for part in text.split(";") if part.strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _column_index_map(headers: list[str]) -> dict[str, int]:
    """Map LibGen column header names to cell indices.

    The real LibGen results table inserts a *Publisher* column before
    *Year*: ``ID, Authors, Title, Publisher, Year, Pages, Language,
    Size, Extension``.  Mapping by header name (instead of fixed
    positions) keeps parsing correct across mirrors that add/remove
    trailing columns (``Mirrors``, ``Edit``, ...).
    """
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        h = header.strip().lower()
        if h in ("id", "libgen id") and "id" not in mapping:
            mapping["id"] = idx
        elif h in ("author", "authors", "author(s)") and "authors" not in mapping:
            mapping["authors"] = idx
        elif h == "title" and "title" not in mapping:
            mapping["title"] = idx
        elif h == "year" and "year" not in mapping:
            mapping["year"] = idx
        elif h in ("extension", "ext", "ext.", "format") and "extension" not in mapping:
            mapping["extension"] = idx
    return mapping


def _cell(cells: list[str], index: int | None, default: str = "") -> str:
    """Return ``cells[index]`` (or *default* when out of range / unknown)."""
    if index is None or index < 0 or index >= len(cells):
        return default
    return cells[index]


def _parse_libgen_results(html: str, limit: int) -> list[SourceSearchResult]:
    """Parse LibGen's HTML results table into SourceSearchResult items."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="c")
    if table is None:
        return []
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    col = _column_index_map(header_cells)
    if "title" not in col:
        # Legacy positional fallback: ID, Authors, Title, Year, Pages,
        # Language, Size, Extension (no Publisher column).
        col = {"id": 0, "authors": 1, "title": 2, "year": 3, "extension": 7}

    results: list[SourceSearchResult] = []
    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if not cells:
            continue
        title = _cell(cells, col.get("title"))
        if not title:
            continue
        authors = _split_author_names(_cell(cells, col.get("authors")))
        results.append(
            SourceSearchResult(
                type="book",
                identifier=f"md5:{_cell(cells, col.get('id'), cells[0] if cells else '')}",
                title=title,
                authors=authors,
                year=_parse_year(_cell(cells, col.get("year"))),
                source_index="libgen",
                source_index_label="Library Genesis (LibGen)",
                relevance_score=None,
                file_type=_cell(cells, col.get("extension")) or None,
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

        import httpx

        client: Any = self._http
        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
            close_client = True

        try:
            resp = await client.post(
                LIBGEN_SEARCH_URL,
                data={"req": query, "res": 25, "view": "simple"},
                timeout=DEFAULT_TIMEOUT,
            )

            if getattr(resp, "status_code", None) != 200:
                logger.warning(
                    "LibGen returned HTTP %r for %r",
                    getattr(resp, "status_code", None), query,
                )
                return []

            return _parse_libgen_results(getattr(resp, "text", "") or "", limit)
        except Exception:
            logger.exception("LibGen search failed for %r", query)
            return []
        finally:
            if close_client:
                await client.aclose()

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

    # ── full-text download ────────────────────────────────────────

    async def fetch_fulltext(self, result: SourceSearchResult) -> FulltextFetchResult | None:
        """Download a LibGen file by MD5/ID link (fail-closed)."""
        from research_shared.adapters.download import download_bytes

        url = result.download_url
        if not url:
            md5 = _libgen_md5(result)
            if not md5:
                return None
            url = f"{LIBGEN_DOWNLOAD_URL}?md5={md5}"

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


def _libgen_md5(result: SourceSearchResult) -> str | None:
    """Extract the MD5 from a LibGen result identifier (``md5:...``)."""
    identifier = (result.identifier or "").removeprefix("md5:")
    return identifier or None
