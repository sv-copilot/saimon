"""libgen.py — Library Genesis (LibGen) source index adapter.

LibGen (libgen.li, .vg, .la, .bz, .gl) is a community-uploaded
repository of academic papers and books.  Search is via HTML form
submission; results are paginated HTML tables.

Tier: S — core source index with high metadata quality.
"""

from __future__ import annotations

import logging
from typing import Any

from research_shared.adapters.base import SourceSearchResult

logger = logging.getLogger("saimon.adapters.libgen")


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

        POSTs to libgen.li/index.php and parses the HTML results table.
        Returns real metadata on success, empty list on failure.
        """
        if not query.strip():
            return []

        logger.debug("LibGen search: %r (limit=%d)", query, limit)

        if self._http is None:
            import httpx
            client = httpx.AsyncClient()
        else:
            client = self._http

        try:
            resp = await client.post(
                "https://libgen.li/index.php",
                data={"req": query, "res": min(limit, 25), "view": "simple"},
                timeout=20.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Saimon/1.0; research-bot)",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "LibGen returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            # LibGen results are in a table with class 'c'
            rows = soup.select("table.c tr, table[class*='c'] tr")
            # Skip header row
            data_rows = rows[1:] if len(rows) > 1 else []

            results: list[SourceSearchResult] = []
            for row in data_rows[:limit]:
                try:
                    cols = row.find_all("td")
                    if len(cols) < 8:
                        continue

                    title = cols[2].get_text(strip=True) if len(cols) > 2 else "Untitled"
                    authors_text = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                    authors = [a.strip() for a in authors_text.split(",") if a.strip()] if authors_text else []
                    year_text = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                    year = int(year_text) if year_text.isdigit() else None
                    file_type = cols[7].get_text(strip=True).lower() if len(cols) > 7 else None

                    # Try to get MD5 from download link
                    md5_link = row.select_one("a[href*='md5=']")
                    md5 = None
                    if md5_link:
                        href = md5_link.get("href", "")
                        if "md5=" in href:
                            md5 = href.split("md5=")[-1].split("&")[0]

                    results.append(
                        SourceSearchResult(
                            type="academic_paper" if year else "book",
                            identifier=f"md5:{md5}" if md5 else f"lg:{query.replace(' ', '-')}",
                            title=title,
                            authors=authors,
                            year=year,
                            source_index=self.name,
                            source_index_label="Library Genesis (LibGen)",
                            relevance_score=0.80,
                            file_type=file_type,
                        )
                    )
                except Exception:  # noqa: BLE001 — skip malformed results
                    continue

            return results
        except Exception:
            logger.warning("LibGen search failed", exc_info=True)
            return []
        finally:
            if self._http is None and client is not None:
                await client.aclose()

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via LibGen's scimag collection."""
        if not doi.strip():
            return None

        logger.debug("LibGen DOI resolve: %r", doi)

        try:
            results = await self.search(doi, limit=3)
            for result in results:
                if result.doi == doi or doi.lower() in result.title.lower():
                    return result
            if results:
                results[0].doi = doi
                results[0].identifier = f"doi:{doi}"
                return results[0]
        except Exception:
            logger.warning("LibGen DOI resolve failed", exc_info=True)
        return None
