"""internet_archive.py — Internet Archive source index adapter.

Internet Archive (archive.org) provides a REST API for searching
its digital library of texts, journals, and other media.

Tier: A — strong source index with a real API and good metadata.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from research_shared.adapters.base import SourceSearchResult

logger = logging.getLogger("saimon.adapters.internet_archive")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IA_SEARCH_URL = "https://archive.org/advancedsearch.php"
DEFAULT_ROWS = 10
DEFAULT_TIMEOUT = 15.0  # seconds


class InternetArchiveAdapter:
    """Adapter for Internet Archive (archive.org).

    Uses archive.org's Advanced Search API and Open Library API.
    Has a real, documented REST API — the most straightforward
    integration among all shadow library sources.
    """

    name: str = "internet_archive"
    tier: str = "A"
    trust_model: str = "institutional"

    def __init__(self, http_client: Any = None) -> None:
        self._http = http_client

    # ── search ────────────────────────────────────────────────────

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search Internet Archive for *query*.

        Calls archive.org/advancedsearch.php?q=QUERY&rows=LIMIT&page=PAGE&output=json.
        Returns SourceSearchResult list, or [] on any error.
        """
        if not query.strip():
            return []

        rows = min(limit, DEFAULT_ROWS)
        page = (offset // rows) + 1 if offset else 1
        url = (
            f"{IA_SEARCH_URL}"
            f"?q={quote(query)}"
            f"&rows={rows}"
            f"&page={page}"
            f"&output=json"
        )

        logger.debug("Internet Archive search: %r (limit=%d)", query, limit)

        try:
            client = self._http or httpx
            # httpx.AsyncClient.get returns a Response; httpx.get is sync
            if self._http is not None:
                resp = await client.get(url, timeout=DEFAULT_TIMEOUT)
            else:
                # Fallback to synchronous httpx.get when no client injected
                resp = await _async_get(url)
        except Exception:
            logger.exception("Internet Archive search failed for %r", query)
            return []

        if resp.status_code != 200:
            logger.warning(
                "Internet Archive returned HTTP %d for %r", resp.status_code, query
            )
            return []

        try:
            data = resp.json()
        except Exception:
            logger.exception("Internet Archive JSON parse failed for %r", query)
            return []

        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return []

        results: list[SourceSearchResult] = []
        for doc in docs[:limit]:
            results.append(_parse_doc(doc))

        return results

    # ── DOI resolution ────────────────────────────────────────────

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI via Internet Archive.

        Searches archive.org for the DOI and returns the first match.
        """
        if not doi.strip():
            return None

        url = (
            f"{IA_SEARCH_URL}"
            f"?q={quote(doi)}"
            f"&rows=1"
            f"&output=json"
        )

        logger.debug("Internet Archive DOI resolve: %r", doi)

        try:
            client = self._http or httpx
            if self._http is not None:
                resp = await client.get(url, timeout=DEFAULT_TIMEOUT)
            else:
                resp = await _async_get(url)
        except Exception:
            logger.exception("Internet Archive DOI resolve failed for %r", doi)
            return None

        if resp.status_code != 200:
            return None

        try:
            data = resp.json()
        except ValueError:  # JSON decode failure
            return None

        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return None

        result = _parse_doc(docs[0])
        result.doi = doi  # Override with the requested DOI
        result.identifier = f"doi:{doi}"
        return result

    # ── full-text storage ──────────────────────────────────────────

    async def store_fulltext(
        self,
        storage: Any,
        db: Any,
        *,
        doi: str,
        title: str,
        data: bytes,
        file_type: str | None = None,
    ) -> str | None:
        """Upload full-text bytes to S3 and persist the object key.

        Delegates to the shared ``research_shared.s3_storage`` helper.
        Optional capability — returns None if storage is not configured.
        """
        from research_shared.s3_storage import S3StorageError, store_shadow_fulltext

        try:
            return await store_shadow_fulltext(
                db,
                storage,
                doi=doi,
                title=title,
                data=data,
                file_type=file_type,
                source_index=self.name,
            )
        except S3StorageError as exc:
            logger.warning("Internet Archive full-text store failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_get(url: str, timeout: float = DEFAULT_TIMEOUT) -> httpx.Response:
    """Make an async GET request using httpx.AsyncClient."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.get(url)


def _parse_doc(doc: dict) -> SourceSearchResult:
    """Parse a single IA doc dict into a SourceSearchResult."""
    identifier = doc.get("identifier", "")
    title = doc.get("title", "Untitled").strip()
    creators = doc.get("creator", [])
    if isinstance(creators, str):
        authors = [creators] if creators.strip() else []
    elif isinstance(creators, list):
        authors = [c.strip() for c in creators if c and str(c).strip()]
    else:
        authors = []

    raw_year = doc.get("year")
    year: int | None = None
    if raw_year is not None:
        try:
            year = int(str(raw_year).strip())
        except (ValueError, TypeError):
            year = None

    abstract_snippet: str | None = None
    raw_desc = doc.get("description")
    if raw_desc and str(raw_desc).strip():
        abstract_snippet = str(raw_desc).strip()

    raw_doi = doc.get("doi")
    doi: str | None = None
    if raw_doi and str(raw_doi).strip():
        doi = str(raw_doi).strip()

    mediatype = doc.get("mediatype", "")
    file_type = _map_mediatype(mediatype)

    return SourceSearchResult(
        type="book",
        identifier=f"ia:{identifier}" if identifier else "ia:unknown",
        doi=doi,
        title=title or "Untitled",
        authors=authors,
        year=year,
        abstract_snippet=abstract_snippet,
        source_index="internet_archive",
        source_index_label="Internet Archive",
        relevance_score=None,  # IA doesn't provide relevance scores
        full_text_available=mediatype == "texts",
        file_type=file_type,
    )


def _map_mediatype(mediatype: str) -> str | None:
    """Map IA mediatype to a file extension."""
    mapping = {
        "texts": "pdf",
        "audio": "mp3",
        "movies": "mp4",
        "image": "jpg",
        "software": "zip",
        "data": "json",
        "web": "html",
    }
    return mapping.get(mediatype)
