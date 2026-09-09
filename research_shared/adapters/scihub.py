"""scihub.py — Sci-Hub / SciDB source index adapter.

Sci-Hub is primarily a DOI resolver (not a search engine).  Given a
DOI, it returns the full PDF.  SciDB (accessible via Anna's Archive)
adds a search layer on top of Sci-Hub's corpus.

Tier: S — core source index for DOI-based paper resolution.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

logger = logging.getLogger("saimon.adapters.scihub")

DEFAULT_TIMEOUT = 15.0


class SciHubAdapter:
    """Adapter for Sci-Hub / SciDB.

    Primary use case is DOI resolution.  Search is delegated to
    SciDB via Anna's Archive.
    """

    name: str = "scihub"
    tier: str = "S"
    trust_model: str = "algorithmic"

    def __init__(self, http_client: Any = None) -> None:
        self._http = http_client

    # ── search ────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search SciDB for *query* (delegated to SciDB subset).

        Sci-Hub itself is not a search engine; it is a DOI resolver.
        Honest behaviour: return [] rather than fabricating results.
        """
        return []

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Sci-Hub by scraping the wrapper page.

        Sci-Hub is the canonical DOI resolver for paywalled papers: given
        a DOI it serves an HTML wrapper page embedding the PDF.  This GETs
        that page and extracts the embedded PDF URL.  Returns None on any
        error, non-200 response, or when no PDF can be found — it never
        fabricates a result.

        When no HTTP client is configured the canonical Sci-Hub URL for a
        DOI is deterministic, so callers still get an *unverified*
        resolution URL (``full_text_available=False``).
        """
        if not doi.strip():
            return None

        doi = doi.strip()
        download_url = f"https://sci-hub.ru/{doi}"
        logger.debug("Sci-Hub DOI resolve: %r", doi)

        if self._http is None:
            return SourceSearchResult(
                type="academic_paper",
                identifier=f"doi:{doi}",
                doi=doi,
                title=f"Sci-Hub: {doi}",
                authors=[],
                source_index=self.name,
                source_index_label="Sci-Hub / SciDB",
                relevance_score=None,
                full_text_available=False,
                file_type=None,
                download_url=download_url,
            )

        try:
            resp = await self._http.get(download_url, timeout=DEFAULT_TIMEOUT)
        except Exception:
            logger.exception("Sci-Hub DOI resolve failed for %r", doi)
            return None

        if getattr(resp, "status_code", None) != 200:
            return None

        headers = getattr(resp, "headers", None) or {}
        content_type = (
            headers.get("content-type", "") if isinstance(headers, dict) else ""
        )

        if "pdf" in content_type.lower():
            pdf_url = download_url
        else:
            text = getattr(resp, "text", "") or ""
            pdf_url = _extract_pdf_url_from_text(text)

        if not pdf_url:
            return None

        return SourceSearchResult(
            type="academic_paper",
            identifier=f"doi:{doi}",
            doi=doi,
            title=f"Sci-Hub full text: {doi}",
            authors=[],
            source_index=self.name,
            source_index_label="Sci-Hub / SciDB",
            relevance_score=None,
            full_text_available=True,
            file_type="pdf",
            download_url=pdf_url,
        )

    # ── full-text download ────────────────────────────────────────

    async def fetch_fulltext(self, result: SourceSearchResult) -> FulltextFetchResult | None:
        """Download the PDF for a DOI via Sci-Hub (fail-closed)."""
        from research_shared.adapters.download import download_bytes

        doi = result.doi
        if not doi:
            return None

        url = result.download_url or f"https://sci-hub.ru/{doi}"
        data = await download_bytes(self._http, url)
        if data is None:
            return None

        if data.startswith(b"%PDF") or (result.file_type or "").lower() == "pdf":
            return FulltextFetchResult(
                source_index=self.name,
                doi=doi,
                data=data,
                file_type="pdf",
                download_url=url,
            )

        # HTML wrapper page — extract an embedded PDF link and retry.
        pdf_url = _extract_pdf_url(data)
        if pdf_url:
            pdf_data = await download_bytes(self._http, pdf_url)
            if pdf_data is not None:
                return FulltextFetchResult(
                    source_index=self.name,
                    doi=doi,
                    data=pdf_data,
                    file_type="pdf",
                    download_url=pdf_url,
                )
        return None


_PDF_URL_RE = re.compile(
    r'(?:src|href)=["\']([^"\']+\.pdf(?:[?#][^"\']*)?)["\']',
    re.IGNORECASE,
)

_SCI_HUB_BASE_URL = "https://sci-hub.ru/"


def _extract_pdf_url_from_text(text: str) -> str | None:
    """Extract the first embedded PDF URL (``src``/``href``) from HTML text.

    Resolves relative and protocol-relative URLs against the Sci-Hub base.
    """
    match = _PDF_URL_RE.search(text)
    if not match:
        return None
    url = match.group(1)
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return _SCI_HUB_BASE_URL.rstrip("/") + url
    if url.startswith("http"):
        return url
    return _SCI_HUB_BASE_URL.rstrip("/") + "/" + url


def _extract_pdf_url(html: bytes) -> str | None:
    """Extract the first PDF href from a Sci-Hub HTML wrapper page."""
    try:
        text = html.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001 — best-effort decode
        return None
    return _extract_pdf_url_from_text(text)
