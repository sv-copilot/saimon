"""scotus_merits.py — SCOTUS Merits Briefs source adapter.

Supreme Court merits briefs are public records.  This adapter is public-data
(no API key required) and is always ready; an optional key may be supplied for
rate-limited commercial mirrors.  Tier: S.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from plugins.legal.adapters.base import parse_year
from research_shared.adapters.base import SourceSearchResult

logger = logging.getLogger("saimon.legal.scotus_merits")

SCOTUS_MERITS_URL = "https://api.supremecourt.gov/v1/cases/"


def parse_scotus_results(payload: dict[str, Any]) -> list[SourceSearchResult]:
    """Parse a SCOTUS merits response into SourceSearchResult list."""
    results: list[SourceSearchResult] = []
    for item in payload.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        title = item.get("case_name") or item.get("name") or ""
        if not title:
            continue
        record_id = item.get("id") or item.get("docket_number")
        results.append(
            SourceSearchResult(
                type="legal_document",
                identifier=(
                    f"scotus:{record_id}"
                    if record_id is not None
                    else f"scotus:{title}"
                ),
                title=title,
                year=parse_year(item.get("term") or item.get("date")),
                source_index="scotus_merits",
                source_index_label="SCOTUS Merits Briefs",
            )
        )
    return results


class ScotusMeritsAdapter:
    """Adapter for Supreme Court merits briefs (public data)."""

    name = "scotus_merits"
    tier = "S"
    trust_model = "institutional"

    def __init__(
        self, api_key: str | None = None, http_client: Any = None
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.getenv("SCOTUS_API_KEY")
        )
        self._http = http_client

    def readiness(self) -> dict[str, str]:
        # SCOTUS merits briefs are public records — no key required.
        return {
            "status": "ready",
            "details": "SCOTUS merits briefs are public; no key required",
        }

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        if not query.strip():
            return []
        if self._http is None:
            logger.warning("SCOTUS merits search skipped: no HTTP client")
            return []
        try:
            resp = await self._http.get(
                SCOTUS_MERITS_URL, params={"q": query}, timeout=15.0
            )
        except Exception:
            logger.exception("SCOTUS merits search failed for %r", query)
            return []
        if getattr(resp, "status_code", None) != 200:
            logger.warning(
                "SCOTUS merits returned HTTP %r",
                getattr(resp, "status_code", None),
            )
            return []
        return parse_scotus_results(resp.json())

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        return None
