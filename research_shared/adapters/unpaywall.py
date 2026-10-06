"""unpaywall.py — Unpaywall adapter: DOI resolution to lawful open copies.

Unpaywall answers one question well: *given a DOI, is there an openly available
copy of this work, and where is it?* This adapter does exactly that and nothing
more, because that is all the service still offers:

- **Its search endpoint was retired on 18 September 2026.** ``/v2/search`` now
  answers ``410 Gone``, and Unpaywall's own documentation directs callers to
  OpenAlex, which carries the same open-access data. Calling it would be calling
  a dead endpoint, so this adapter never does — ``search`` is implemented as a
  documented no-op rather than a request that cannot work.
- **It requires the caller's own email address.** Requests without one, or with
  a placeholder, are refused by the API (``422 Please use your own email address
  in API calls``). This adapter therefore has no default identity: without a
  configured contact address it declines to call at all, rather than sending
  somebody else's name or a made-up one.

That combination makes it the right choice for resolving a bare DOI
(``DEFAULT_DOI_SOURCE`` at the composition point) and the wrong choice for
searching.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.adapters.unpaywall")

UNPAYWALL_DOI_URL = "https://api.unpaywall.org/v2"
DEFAULT_TIMEOUT = 25.0
RETRIABLE_EXCEPTIONS = (httpx.ReadTimeout, httpx.ConnectError)

#: Environment variable a deployment uses to identify itself to the API. The
#: vendor's terms require a real contact address, so this is configuration, not a
#: default.
CONTACT_EMAIL_ENV = "SAIMON_CONTACT_EMAIL"


def _normalise_doi(raw: str | None) -> str | None:
    """Return a bare DOI from any of the forms callers pass in."""
    if not raw:
        return None
    doi = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.lower() or None


class UnpaywallAdapter:
    """Resolve DOIs to openly available copies.

    Satisfies :class:`research_shared.adapters.base.SourceIndexAdapter`, but
    ``search`` returns nothing by design — see the module docstring.
    """

    name: str = "unpaywall"
    tier: str = "A"
    trust_model: str = "institutional"
    label: str = "Unpaywall"
    kind: str = "paper"
    #: Reaching it requires an identity of the caller's own.
    access: str = "credentialed"

    def __init__(self, email: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.email = (email or os.environ.get(CONTACT_EMAIL_ENV, "")).strip() or None
        self.timeout = timeout
        if self.email is None:
            logger.info(
                "unpaywall_no_contact_email: set %s to enable DOI resolution",
                CONTACT_EMAIL_ENV,
            )

    @property
    def available(self) -> bool:
        """Whether this adapter can call the API at all."""
        return self.email is not None

    async def _get(self, url: str, params: dict[str, Any]) -> httpx.Response | None:
        """GET with one retry on transport errors; None on any failure."""
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params)
                if response.status_code == 404:
                    return None
                if response.status_code == 422:
                    # The vendor refusing the caller's identity is not retriable.
                    logger.warning("unpaywall_rejected_request url=%s", url)
                    return None
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "unpaywall_http_error status=%s url=%s", exc.response.status_code, url
                )
                return None
            except RETRIABLE_EXCEPTIONS:
                if attempt == 2:
                    logger.warning("unpaywall_unreachable url=%s", url)
                    return None
        return None

    @staticmethod
    def _to_result(payload: dict[str, Any], doi: str) -> SourceSearchResult:
        """Map a Unpaywall DOI object onto the canonical result shape."""
        best = payload.get("best_oa_location") or {}
        oa_locations = [loc for loc in (payload.get("oa_locations") or []) if isinstance(loc, dict)]
        pdf_url = (best.get("url_for_pdf") or best.get("url") or "") or None
        if pdf_url is None:
            for loc in oa_locations:
                if loc.get("url_for_pdf"):
                    pdf_url = loc["url_for_pdf"]
                    break

        title = (payload.get("title") or "").strip() or f"Unpaywall record for {doi}"
        authors = [
            (author or {}).get("raw_author_name") or ""
            for author in (payload.get("z_authors") or [])
        ]
        year = payload.get("year")

        return SourceSearchResult(
            type="academic_paper",
            identifier=f"doi:{doi}",
            doi=doi,
            title=title,
            authors=[a for a in authors if a],
            year=year if isinstance(year, int) else None,
            source_index=UnpaywallAdapter.name,
            source_index_label=UnpaywallAdapter.label,
            full_text_available=bool(payload.get("is_oa")) and bool(pdf_url),
            file_type="pdf" if pdf_url else None,
            download_url=pdf_url,
        )

    # ── protocol ──────────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Always empty: Unpaywall has no search endpoint to call.

        This is a documented no-op, not a failure. A deployment that wants this
        source searched wants OpenAlex, which carries Unpaywall's data.
        """
        logger.debug("unpaywall_search_unsupported query=%r", query[:60])
        return []

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI to its open-access status and copy, if any."""
        bare = _normalise_doi(doi)
        if not bare or not self.available:
            return None
        response = await self._get(f"{UNPAYWALL_DOI_URL}/{bare}", {"email": self.email})
        if response is None:
            return None
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("doi"):
            return None
        return self._to_result(payload, bare)

    async def fetch_fulltext(
        self, result: SourceSearchResult
    ) -> FulltextFetchResult | None:
        """Fetch the open copy of *result*, when the API reported one."""
        if not result.download_url:
            return None
        response = await self._get(result.download_url, {})
        if response is None or not response.content:
            return None
        return FulltextFetchResult(
            source_index=self.name,
            doi=result.doi,
            data=response.content,
            file_type=result.file_type or "pdf",
            download_url=result.download_url,
        )
