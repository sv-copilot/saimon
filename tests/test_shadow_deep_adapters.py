"""Recorded-fixture tests for SAIMON-SHADOW-DEEP-1.

The three "deep" shadow-library adapters — Anna's Archive, LibGen, and
Sci-Hub — must make real HTTP requests and return parsed
``SourceSearchResult`` objects from recorded HTML fixtures, degrade to an
empty list (or ``None`` for DOI resolution) on any failure, and carry
tier / trust_model metadata.

All HTTP is mocked — no live network. Fixtures live under
``tests/fixtures/shadow_deep/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.base import SourceSearchResult
from research_shared.adapters.libgen import LibGenAdapter
from research_shared.adapters.scihub import SciHubAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "shadow_deep"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", headers: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeClient:
    """Minimal async HTTP client that returns one canned response per verb."""

    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None) -> None:
        self._response = response or FakeResponse(status_code=404)
        self.error = error
        self.get_calls: list[str] = []
        self.post_calls: list[str] = []

    async def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append(url)
        if self.error is not None:
            raise self.error
        return self._response

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append(url)
        if self.error is not None:
            raise self.error
        return self._response


def _client(text: str = "", status: int = 200, headers: dict | None = None, error: Exception | None = None) -> FakeClient:
    return FakeClient(FakeResponse(status_code=status, text=text, headers=headers), error=error)


# ---------------------------------------------------------------------------
# Anna's Archive
# ---------------------------------------------------------------------------


class TestAnnasArchiveDeep:
    async def test_search_parses_recorded_fixture(self) -> None:
        """A recorded AA search page yields parsed SourceSearchResults."""
        adapter = AnnasArchiveAdapter(http_client=_client(text=_load("annas_archive_search.html")))

        results = await adapter.search("attention is all you need", limit=5)

        assert isinstance(results, list)
        assert len(results) == 2
        first = results[0]
        assert isinstance(first, SourceSearchResult)
        assert first.title == "Attention Is All You Need"
        assert first.identifier == "md5:4d3a8f1c9b2e7a6d5f0e1c2b3a495867"
        assert first.authors == ["Vaswani, Ashish", "Shazeer, Noam", "Parmar, Niki"]
        assert first.year == 2017
        assert first.file_type == "pdf"
        assert first.full_text_available is True
        assert first.source_index == "annas_archive"
        assert first.source_index_label == "Anna's Archive"

    async def test_search_http_error_returns_empty(self) -> None:
        """Non-200 → [] (no crash, no fabricated results)."""
        adapter = AnnasArchiveAdapter(http_client=_client(status=403))
        assert await adapter.search("attention is all you need") == []

    async def test_search_network_error_returns_empty(self) -> None:
        """Network failure → []."""
        adapter = AnnasArchiveAdapter(
            http_client=_client(error=Exception("connection reset"))
        )
        assert await adapter.search("attention is all you need") == []

    def test_tier_and_trust_model(self) -> None:
        adapter = AnnasArchiveAdapter()
        assert adapter.tier == "S"
        assert adapter.trust_model == "algorithmic"


# ---------------------------------------------------------------------------
# LibGen
# ---------------------------------------------------------------------------


class TestLibGenDeep:
    async def test_search_parses_recorded_fixture(self) -> None:
        """A recorded LibGen results table (with Publisher column) parses correctly."""
        adapter = LibGenAdapter(http_client=_client(text=_load("libgen_search.html")))

        results = await adapter.search("attention is all you need", limit=5)

        assert isinstance(results, list)
        assert len(results) == 2
        first = results[0]
        assert isinstance(first, SourceSearchResult)
        assert first.title == "Attention Is All You Need"
        assert first.authors == ["Vaswani, Ashish", "Shazeer, Noam"]
        # The real LibGen layout inserts Publisher before Year; year must come
        # from the "Year" column, not the Publisher column.
        assert first.year == 2017
        assert first.file_type == "pdf"
        assert first.source_index == "libgen"
        assert first.source_index_label == "Library Genesis (LibGen)"

    async def test_search_http_error_returns_empty(self) -> None:
        """Non-200 → []."""
        adapter = LibGenAdapter(http_client=_client(status=500))
        assert await adapter.search("attention is all you need") == []

    async def test_search_network_error_returns_empty(self) -> None:
        """Network failure → []."""
        adapter = LibGenAdapter(http_client=_client(error=Exception("connection refused")))
        assert await adapter.search("attention is all you need") == []

    def test_tier_and_trust_model(self) -> None:
        adapter = LibGenAdapter()
        assert adapter.tier == "S"
        assert adapter.trust_model == "community"


# ---------------------------------------------------------------------------
# Sci-Hub
# ---------------------------------------------------------------------------


class TestSciHubDeep:
    async def test_resolve_doi_scrapes_pdf_from_fixture(self) -> None:
        """A recorded Sci-Hub wrapper page yields the embedded PDF URL."""
        adapter = SciHubAdapter(http_client=_client(text=_load("scihub_resolve.html")))

        result = await adapter.resolve_doi("10.1038/s41586-023-06004-z")

        assert result is not None
        assert isinstance(result, SourceSearchResult)
        assert result.doi == "10.1038/s41586-023-06004-z"
        assert result.full_text_available is True
        assert result.file_type == "pdf"
        assert result.download_url is not None
        assert "paper.pdf" in result.download_url
        assert result.source_index == "scihub"
        assert result.source_index_label == "Sci-Hub / SciDB"

    async def test_search_returns_empty_honestly(self) -> None:
        """Sci-Hub is a DOI resolver, not a search engine — search stays honest."""
        adapter = SciHubAdapter(http_client=_client())
        assert await adapter.search("anything") == []

    async def test_resolve_doi_not_found_returns_none(self) -> None:
        """A 404 (no record) → None, never a fabricated result."""
        adapter = SciHubAdapter(http_client=_client(status=404))
        assert await adapter.resolve_doi("10.9999/does-not-exist") is None

    async def test_resolve_doi_network_error_returns_none(self) -> None:
        """Network failure → None."""
        adapter = SciHubAdapter(http_client=_client(error=Exception("timeout")))
        assert await adapter.resolve_doi("10.1038/s41586-023-06004-z") is None

    def test_tier_and_trust_model(self) -> None:
        adapter = SciHubAdapter()
        assert adapter.tier == "S"
        assert adapter.trust_model == "algorithmic"


# ---------------------------------------------------------------------------
# Cross-adapter tier / trust metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter_cls,tier,trust_model",
    [
        (AnnasArchiveAdapter, "S", "algorithmic"),
        (LibGenAdapter, "S", "community"),
        (SciHubAdapter, "S", "algorithmic"),
    ],
)
def test_deep_adapters_honor_tier_and_trust_model(adapter_cls, tier, trust_model) -> None:
    """All three deep adapters carry tier + trust_model metadata."""
    adapter = adapter_cls()
    assert adapter.tier == tier
    assert adapter.trust_model == trust_model
