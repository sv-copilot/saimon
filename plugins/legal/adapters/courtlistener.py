"""courtlistener.py — CourtListener source adapter.

CourtListener (https://www.courtlistener.com) is a free legal research
database with a REST API covering opinions, dockets, RECAP briefs, and citator
data.  Tier: S.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from plugins.legal.adapters.base import parse_year
from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.legal.courtlistener")

COURTLISTENER_SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"


def parse_courtlistener_results(
    payload: dict[str, Any],
) -> list[SourceSearchResult]:
    """Parse a CourtListener search response into SourceSearchResult list."""
    results: list[SourceSearchResult] = []
    for item in payload.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        title = item.get("name") or item.get("caseName") or ""
        if not title:
            continue
        record_id = item.get("id")
        results.append(
            SourceSearchResult(
                type="legal_case",
                identifier=(
                    f"cl:{record_id}" if record_id is not None else f"cl:{title}"
                ),
                title=title,
                year=parse_year(item.get("date_filed") or item.get("dateFiled")),
                source_index="courtlistener",
                source_index_label="CourtListener",
            )
        )
    return results


class CourtListenerAdapter:
    """Adapter for CourtListener opinions, dockets, and citator data."""

    name = "courtlistener"
    tier = "S"
    trust_model = "institutional"

    def __init__(
        self, api_key: str | None = None, http_client: Any = None
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.getenv("COURTLISTENER_API_KEY")
        )
        self._http = http_client

    def readiness(self) -> dict[str, str]:
        if not self._api_key:
            return {
                "status": "missing_config",
                "details": "CourtListener needs COURTLISTENER_API_KEY",
            }
        return {"status": "ready", "details": "CourtListener configured"}

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        if not query.strip():
            return []
        if not self._api_key:
            logger.warning("CourtListener search skipped: no API key")
            return []
        if self._http is None:
            logger.warning("CourtListener search skipped: no HTTP client")
            return []
        try:
            resp = await self._http.get(
                COURTLISTENER_SEARCH_URL,
                params={"q": query, "type": "o"},
                timeout=15.0,
            )
        except Exception:
            logger.exception("CourtListener search failed for %r", query)
            return []
        if getattr(resp, "status_code", None) != 200:
            logger.warning(
                "CourtListener returned HTTP %r",
                getattr(resp, "status_code", None),
            )
            return []
        return parse_courtlistener_results(resp.json())

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        return None

    async def fetch_fulltext(self, result: SourceSearchResult) -> FulltextFetchResult | None:
        """Legal indexes do not expose downloadable full text — return None."""
        return None
