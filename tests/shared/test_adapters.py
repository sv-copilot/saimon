"""Tests for shadow library adapters — all 5 adapter implementations."""

import pytest

from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.base import SourceSearchResult


# ---------------------------------------------------------------------------
# Adapter list for parameterized tests
# ---------------------------------------------------------------------------

ADAPTERS = [InternetArchiveAdapter]

ADAPTER_NAMES = [cls().name for cls in ADAPTERS]


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestAdapterProtocol:
    """Every adapter must satisfy the SourceIndexAdapter protocol."""

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    def test_has_name(self, adapter_cls):
        adapter = adapter_cls()
        assert isinstance(adapter.name, str)
        assert len(adapter.name) > 0

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    def test_has_tier(self, adapter_cls):
        adapter = adapter_cls()
        assert adapter.tier in ("S", "A", "B", "C")

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    def test_has_trust_model(self, adapter_cls):
        adapter = adapter_cls()
        assert adapter.trust_model in ("algorithmic", "community", "institutional")

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_search_is_async_callable(self, adapter_cls):
        adapter = adapter_cls()
        assert callable(adapter.search)
        results = await adapter.search("test query")
        assert isinstance(results, list)

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_resolve_doi_is_async_callable(self, adapter_cls):
        adapter = adapter_cls()
        assert callable(adapter.resolve_doi)
        result = await adapter.resolve_doi("10.1038/test")
        assert result is None or isinstance(result, SourceSearchResult)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestAdapterSearch:
    """Search behavior shared across all adapters."""

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_search_returns_source_search_results(self, adapter_cls):
        """Search returns a list of SourceSearchResult."""
        adapter = adapter_cls()
        results = await adapter.search("machine learning", limit=3)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, SourceSearchResult)
            assert r.source_index == adapter.name
            assert len(r.title) > 0

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_search_empty_query_returns_empty(self, adapter_cls):
        """Empty query returns empty list, not an error."""
        adapter = adapter_cls()
        results = await adapter.search("")
        assert results == []

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_search_whitespace_query_returns_empty(self, adapter_cls):
        """Whitespace-only query returns empty list."""
        adapter = adapter_cls()
        results = await adapter.search("   ")
        assert results == []

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_search_respects_limit(self, adapter_cls):
        """Results don't exceed the requested limit."""
        adapter = adapter_cls()
        results = await adapter.search("test", limit=3)
        assert len(results) <= 3

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_search_relevance_scores_in_range(self, adapter_cls):
        """All relevance scores are in 0.0–1.0 range."""
        adapter = adapter_cls()
        results = await adapter.search("test", limit=5)
        for r in results:
            if r.relevance_score is not None:
                assert 0.0 <= r.relevance_score <= 1.0


# ---------------------------------------------------------------------------
# DOI resolution
# ---------------------------------------------------------------------------


class TestAdapterResolveDOI:
    """DOI resolution behavior."""

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_resolve_doi_returns_result_or_none(self, adapter_cls):
        """resolve_doi returns a SourceSearchResult or None."""
        adapter = adapter_cls()
        result = await adapter.resolve_doi("10.1038/s41586-023-06004-z")
        assert result is None or isinstance(result, SourceSearchResult)

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_resolve_doi_empty_returns_none(self, adapter_cls):
        """Empty DOI returns None."""
        adapter = adapter_cls()
        result = await adapter.resolve_doi("")
        assert result is None

    @pytest.mark.parametrize("adapter_cls", ADAPTERS)
    async def test_resolve_doi_whitespace_returns_none(self, adapter_cls):
        """Whitespace DOI returns None."""
        adapter = adapter_cls()
        result = await adapter.resolve_doi("   ")
        assert result is None


# ---------------------------------------------------------------------------
# Tier-specific
# ---------------------------------------------------------------------------


