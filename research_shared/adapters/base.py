"""base.py — the source adapter contract.

`SourceIndexAdapter` is the protocol every source adapter implements, and
`SourceSearchResult` is the uniform shape adapters return. Services depend on
these two things and on nothing else, which is what lets a deployment change its
sources without touching them.

Writing an adapter for a source you are entitled to reach: implement the
protocol, register it at your composition point, and declare its `access` so
callers know whether it needs your credentials.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# SourceSearchResult
# ---------------------------------------------------------------------------


class SourceSearchResult(BaseModel):
    """A single search result from a source index.

    Used by every adapter to return a uniform shape regardless of the underlying
    source.
    """

    type: str = Field(..., description="Source kind: academic_paper, book, dataset, etc.")
    identifier: str = Field(..., description="Canonical identifier: 'doi:10.xxx' or 'md5:abc123'.")
    doi: str | None = Field(default=None, description="DOI if available.")
    title: str = Field(..., min_length=1, description="Title of the work.")
    authors: list[str] = Field(default_factory=list, description="Author names.")
    year: int | None = Field(default=None, description="Publication year.")
    abstract_snippet: str | None = Field(default=None, description="Abstract or snippet.")
    source_index: str = Field(..., description="Adapter identifier, e.g. 'openalex' or 'my_source'.")
    source_index_label: str = Field(..., description="Human-readable label, e.g. 'OpenAlex'.")
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Relevance score 0.0–1.0.")
    full_text_available: bool = Field(default=False, description="Whether full text is downloadable.")
    file_type: str | None = Field(default=None, description="File type: 'pdf', 'epub', 'djvu', etc.")
    download_url: str | None = Field(default=None, description="Direct or proxied download URL.")

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# FulltextFetchResult
# ---------------------------------------------------------------------------


class FulltextFetchResult(BaseModel):
    """Result of a full-text fetch from a source index.

    ``data`` holds the fetched bytes. Sources that can only hand back a location
    (a landing page, an archive item, a torrent) return ``data=None`` and surface
    a ``download_url`` instead.
    """

    source_index: str = Field(..., description="Adapter identifier that produced this result.")
    doi: str | None = Field(default=None, description="DOI if available.")
    data: bytes | None = Field(default=None, description="Raw fetched bytes.")
    file_type: str | None = Field(default=None, description="File type: 'pdf', 'txt', 'epub', 'djvu', 'torrent'.")
    download_url: str | None = Field(default=None, description="Direct or magnet URL when bytes are unavailable.")

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# SourceIndexAdapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SourceIndexAdapter(Protocol):
    """Protocol that every source adapter must satisfy.

    Each adapter knows how to search one source index and, optionally, resolve a
    DOI to a full result and fetch a work's full text.

    Required: ``name``, ``tier``, ``trust_model`` and ``search``.
    Optional: ``label``, ``kind`` and ``access`` (``"anonymous"``, ``"credentialed"``,
    ``"institutional"``, ``"local"``) — read them through the helpers
    in :mod:`research_shared.source_registry` so an adapter that declares none of
    them still works.
    """

    name: str
    tier: str  # "S", "A", "B", "C" — the adapter's own relevance-weight class
    trust_model: str  # "algorithmic", "community", "institutional"

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search this source index and return ranked results."""
        ...

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI to a full result, or None if not found."""
        ...

    async def fetch_fulltext(
        self, result: SourceSearchResult
    ) -> FulltextFetchResult | None:
        """Fetch the full text of *result*.

        Optional capability. Returns None (never raises) when full text cannot be
        fetched or the source does not support it.
        """
        ...
