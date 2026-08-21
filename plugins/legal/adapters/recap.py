"""recap.py — RECAP brief/document extraction adapter.

RECAP (https://www.courtlistener.com/recap/) is CourtListener's archive of
PACER documents.  Tier: S.  Uses the CourtListener REST API; requires a
RECAP/CourtListener token.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from plugins.legal.adapters.base import parse_year
from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.legal.recap")

RECAP_SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/recap/search/"


def parse_recap_results(payload: dict[str, Any]) -> list[SourceSearchResult]:
    """Parse a RECAP search response into SourceSearchResult list."""
    results: list[SourceSearchResult] = []
    for item in payload.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        title = item.get("description") or item.get("document_number") or ""
        if not title:
            continue
        record_id = item.get("id")
        results.append(
            SourceSearchResult(
                type="legal_document",
                identifier=(
                    f"recap:{record_id}"
                    if record_id is not None
                    else f"recap:{title}"
                ),
                title=str(title),
                year=parse_year(item.get("date_filed")),
                source_index="recap",
                source_index_label="RECAP",
            )
        )
    return results


class RecapAdapter:
    """Adapter for RECAP brief and docket-document extraction."""

    name = "recap"
    tier = "S"
    trust_model = "institutional"

    def __init__(
        self, api_key: str | None = None, http_client: Any = None
    ) -> None:
        self._api_key = (
            api_key
            if api_key is not None
            else (os.getenv("RECAP_API_KEY") or os.getenv("COURTLISTENER_API_KEY"))
        )
        self._http = http_client

    def readiness(self) -> dict[str, str]:
        if not self._api_key:
            return {
                "status": "missing_config",
                "details": "RECAP needs RECAP_API_KEY or COURTLISTENER_API_KEY",
            }
        return {"status": "ready", "details": "RECAP configured"}

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        if not query.strip():
            return []
        if not self._api_key:
            logger.warning("RECAP search skipped: no API key")
            return []
        if self._http is None:
            logger.warning("RECAP search skipped: no HTTP client")
            return []
        try:
            resp = await self._http.get(
                RECAP_SEARCH_URL, params={"q": query}, timeout=15.0
            )
        except Exception:
            logger.exception("RECAP search failed for %r", query)
            return []
        if getattr(resp, "status_code", None) != 200:
            logger.warning(
                "RECAP returned HTTP %r", getattr(resp, "status_code", None)
            )
            return []
        return parse_recap_results(resp.json())

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        return None

    async def fetch_fulltext(self, result: SourceSearchResult) -> FulltextFetchResult | None:
        """Legal indexes do not expose downloadable full text — return None."""
        return None
