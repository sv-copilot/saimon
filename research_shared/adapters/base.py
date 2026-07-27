"""base.py — shared adapter protocol and SourceSearchResult model.

Every shadow library adapter implements SourceIndexAdapter.
SourceSearchResult is the canonical search result shape returned
by all adapters.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# SourceSearchResult
# ---------------------------------------------------------------------------


class SourceSearchResult(BaseModel):
    """A single search result from a source index.

    Used by all shadow library adapters to return a uniform shape
    regardless of the underlying source.
    """

    type: str = Field(..., description="Source kind: academic_paper, book, dataset, etc.")
    identifier: str = Field(..., description="Canonical identifier: 'doi:10.xxx' or 'md5:abc123'.")
    doi: str | None = Field(default=None, description="DOI if available.")
    title: str = Field(..., min_length=1, description="Title of the work.")
    authors: list[str] = Field(default_factory=list, description="Author names.")
    year: int | None = Field(default=None, description="Publication year.")
    abstract_snippet: str | None = Field(default=None, description="Abstract or snippet.")
    source_index: str = Field(..., description="Adapter identifier: 'annas_archive', 'libgen', etc.")
    source_index_label: str = Field(..., description="Human-readable label: 'Anna\'s Archive', 'LibGen', etc.")
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Relevance score 0.0–1.0.")
    full_text_available: bool = Field(default=False, description="Whether full text is downloadable.")
    file_type: str | None = Field(default=None, description="File type: 'pdf', 'epub', 'djvu', etc.")
    download_url: str | None = Field(default=None, description="Direct or proxied download URL.")

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# SourceIndexAdapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SourceIndexAdapter(Protocol):
    """Protocol that every shadow library adapter must satisfy.

    Each adapter knows how to search a specific source index and
    optionally resolve a DOI to a full result.
    """

    name: str
    tier: str  # "S", "A", "B", "C"
    trust_model: str  # "algorithmic", "community", "institutional"

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Search this source index and return ranked results."""
        ...

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve a DOI to a full result, or None if not found."""
        ...
