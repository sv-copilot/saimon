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

        Currently returns placeholder results.  Production would POST
        to libgen.li/index.php and parse the HTML table response.
        """
        if not query.strip():
            return []

        _ = (self._http, offset)  # reserved
        logger.debug("LibGen search: %r (limit=%d)", query, limit)

        results: list[SourceSearchResult] = []
        for i in range(min(limit, 5)):
            results.append(
                SourceSearchResult(
                    type="book",
                    identifier=f"md5:lg-placeholder-{i}",
                    title=f"LibGen result {i + 1} for: {query}",
                    authors=[f"Author {chr(65 + i)}"],
                    year=2018 + i,
                    source_index=self.name,
                    source_index_label="Library Genesis (LibGen)",
                    relevance_score=round(0.90 - i * 0.1, 2),
                    file_type="pdf" if i % 2 == 0 else "epub",
                )
            )
        return results

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via LibGen.

        LibGen stores DOIs in its scimag (scientific articles) collection.
        """
        if not doi.strip():
            return None

        _ = self._http  # reserved
        logger.debug("LibGen DOI resolve: %r", doi)

        return SourceSearchResult(
            type="academic_paper",
            identifier=f"doi:{doi}",
            doi=doi,
            title=f"LibGen paper for DOI: {doi}",
            authors=["Author, B."],
            source_index=self.name,
            source_index_label="Library Genesis (LibGen)",
            relevance_score=0.90,
            full_text_available=True,
            file_type="pdf",
        )
