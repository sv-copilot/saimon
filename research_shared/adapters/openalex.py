"""openalex.py — OpenAlex source index adapter.

OpenAlex is an open scholarly index: works, authors, institutions, and the
open-access status of each work. No API key is required to search it; the API
asks that you identify yourself with your email in a `mailto` parameter, which
this adapter sends when the deployment configures one.

Three details of the real API shape matter here, each verified against the
vendor's documentation rather than assumed:

- Abstracts are **not** returned as text. They arrive as an
  ``abstract_inverted_index`` — each word mapped to the positions it occurs at —
  which the caller reconstructs. OpenAlex states it does not ship plaintext
  abstracts for legal reasons.
- ``doi`` arrives as a URL (``https://doi.org/10.xxxx``), not a bare DOI, so it
  is normalised before it is stored or cited.
- Full text is only available for works that have an openly available copy, and
  ``content_urls.pdf`` (a separate, metered, keyed endpoint) is deliberately not
  used: the openly available location is enough, and does not require anyone's
  credentials.

Declared ``tier`` reflects how much weight a result from here deserves, and
``access = "anonymous"`` because reaching it needs no account.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.adapters.openalex")

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
DEFAULT_TIMEOUT = 25.0
RETRIABLE_EXCEPTIONS = (httpx.ReadTimeout, httpx.ConnectError)

#: OpenAlex work types mapped to the vocabulary this platform uses. Anything not
#: listed is treated as a paper: the index is overwhelmingly papers, and an
#: unknown type should not silently become something else.
_TYPE_MAP = {
    "article": "academic_paper",
    "review": "academic_paper",
    "preprint": "academic_paper",
    "book": "book",
    "book-chapter": "book",
    "dataset": "dataset",
    "dissertation": "academic_paper",
    "report": "academic_paper",
}


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """Rebuild plaintext from an OpenAlex ``abstract_inverted_index``.

    Each key is a word and each value the positions it occupies. Returns None
    when there is nothing to rebuild, so callers can tell "no abstract" from
    "empty abstract".
    """
    if not inverted_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted_index.items():
        for index in indexes:
            positions.append((index, word))
    if not positions:
        return None
    positions.sort(key=lambda pair: pair[0])
    return " ".join(word for _, word in positions)


def normalise_doi(raw: str | None) -> str | None:
    """Return a bare DOI from any of the forms the API may hand back."""
    if not raw:
        return None
    doi = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.lower() or None


class OpenAlexAdapter:
    """Search and DOI resolution over the OpenAlex index.

    Satisfies :class:`research_shared.adapters.base.SourceIndexAdapter`.
    """

    name: str = "openalex"
    tier: str = "A"
    trust_model: str = "institutional"
    label: str = "OpenAlex"
    kind: str = "mixed"
    access: str = "anonymous"

    def __init__(self, mailto: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        # Sent as the polite `mailto` parameter when the deployment configures a
        # contact address. Absent it the API still answers; this is etiquette,
        # not authentication.
        self.mailto = (mailto or "").strip() or None
        self.timeout = timeout

    # ── internals ─────────────────────────────────────────────────────────

    def _params(self, **extra: Any) -> dict[str, Any]:
        params: dict[str, Any] = dict(extra)
        if self.mailto:
            params["mailto"] = self.mailto
        return params

    async def _get(self, url: str, params: dict[str, Any]) -> httpx.Response | None:
        """GET with one retry on transport errors; None on failure.

        Never raises: an adapter that fails must look like a source with no
        results, not like a broken service.
        """
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                logger.warning("openalex_http_error status=%s url=%s", exc.response.status_code, url)
                return None
            except RETRIABLE_EXCEPTIONS:
                if attempt == 2:
                    logger.warning("openalex_unreachable url=%s", url)
                    return None
        return None

    @staticmethod
    def _to_result(work: dict[str, Any]) -> SourceSearchResult:
        """Map one OpenAlex work onto the canonical result shape."""
        doi = normalise_doi(work.get("doi"))
        open_access = work.get("open_access") or {}
        best_oa = work.get("best_oa_location") or {}
        pdf_url = best_oa.get("url_for_pdf") or best_oa.get("url")
        is_oa = bool(open_access.get("is_oa")) or bool(pdf_url)
        title = (work.get("title") or work.get("display_name") or "").strip() or "(untitled)"

        authors: list[str] = []
        for authorship in work.get("authorships") or []:
            display = ((authorship or {}).get("author") or {}).get("display_name")
            if display:
                authors.append(display)

        return SourceSearchResult(
            type=_TYPE_MAP.get(str(work.get("type") or "").lower(), "academic_paper"),
            identifier=f"doi:{doi}" if doi else str(work.get("id") or ""),
            doi=doi,
            title=title,
            authors=authors,
            year=work.get("publication_year"),
            abstract_snippet=reconstruct_abstract(work.get("abstract_inverted_index")),
            source_index=OpenAlexAdapter.name,
            source_index_label=OpenAlexAdapter.label,
            full_text_available=is_oa,
            file_type="pdf" if pdf_url else None,
            download_url=pdf_url,
        )

    # ── protocol ──────────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search works matching *query*.

        OpenAlex pages with ``page``/``per-page``, so ``offset`` is converted to
        the page that would contain it when ``limit`` divides evenly; otherwise
        the results are trimmed, so the caller still sees exactly ``limit`` items
        from ``offset``.
        """
        if not query or not query.strip() or limit <= 0:
            return []
        per_page = min(max(limit, 1), 200)
        page = (offset // per_page) + 1
        response = await self._get(
            OPENALEX_WORKS_URL,
            self._params(search=query, per_page=per_page, page=page),
        )
        if response is None:
            return []
        payload = response.json()
        works = payload.get("results") or []
        results = [self._to_result(w) for w in works if isinstance(w, dict)]
        # Trim to the requested window when the page starts before the offset.
        trim = offset - (page - 1) * per_page
        return results[trim: trim + limit]

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI to a work, or None when the index does not hold it."""
        bare = normalise_doi(doi)
        if not bare:
            return None
        response = await self._get(f"{OPENALEX_WORKS_URL}/https://doi.org/{bare}", self._params())
        if response is None:
            return None
        work = response.json()
        if not isinstance(work, dict) or not work.get("id"):
            return None
        return self._to_result(work)

    async def fetch_fulltext(
        self, result: SourceSearchResult
    ) -> FulltextFetchResult | None:
        """Fetch the openly available copy of *result*, when there is one.

        Returns None rather than reaching for anything else: a work without an
        open copy is a work this deployment cannot lawfully fetch.
        """
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
