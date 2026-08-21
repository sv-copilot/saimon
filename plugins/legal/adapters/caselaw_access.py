"""caselaw_access.py — Caselaw Access Project source adapter.

The Caselaw Access Project (https://case.law) provides bulk access to
historical U.S. case law.  Tier: S.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from plugins.legal.adapters.base import parse_year
from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.legal.caselaw_access")

CASELAW_ACCESS_URL = "https://api.case.law/v1/cases/"


def parse_caselaw_results(payload: dict[str, Any]) -> list[SourceSearchResult]:
    """Parse a Caselaw Access Project response into SourceSearchResult list."""
    results: list[SourceSearchResult] = []
    for item in payload.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        title = item.get("name") or ""
        if not title:
            continue
        record_id = item.get("id")
        results.append(
            SourceSearchResult(
                type="legal_case",
                identifier=(
                    f"cap:{record_id}" if record_id is not None else f"cap:{title}"
                ),
                title=title,
                year=parse_year(item.get("decision_date")),
                source_index="caselaw_access",
                source_index_label="Caselaw Access Project",
            )
        )
    return results


class CaselawAccessAdapter:
    """Adapter for Caselaw Access Project historical opinions."""

    name = "caselaw_access"
    tier = "S"
    trust_model = "institutional"

    def __init__(
        self, api_key: str | None = None, http_client: Any = None
    ) -> None:
        self._api_key = (
            api_key
            if api_key is not None
            else os.getenv("CASELAW_ACCESS_API_KEY")
        )
        self._http = http_client

    def readiness(self) -> dict[str, str]:
        if not self._api_key:
            return {
                "status": "missing_config",
                "details": "Caselaw Access Project needs CASELAW_ACCESS_API_KEY",
            }
        return {"status": "ready", "details": "Caselaw Access Project configured"}

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        if not query.strip():
            return []
        if not self._api_key:
            logger.warning("Caselaw Access search skipped: no API key")
            return []
        if self._http is None:
            logger.warning("Caselaw Access search skipped: no HTTP client")
            return []
        try:
            resp = await self._http.get(
                CASELAW_ACCESS_URL,
                params={"search": query},
                timeout=15.0,
            )
        except Exception:
            logger.exception("Caselaw Access search failed for %r", query)
            return []
        if getattr(resp, "status_code", None) != 200:
            logger.warning(
                "Caselaw Access returned HTTP %r",
                getattr(resp, "status_code", None),
            )
            return []
        return parse_caselaw_results(resp.json())

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        return None

    async def fetch_fulltext(self, result: SourceSearchResult) -> FulltextFetchResult | None:
        """Legal indexes do not expose downloadable full text — return None."""
        return None
