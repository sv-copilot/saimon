"""Tests for shadow library adapters — all 5 adapter implementations."""

import pytest

from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.libgen import LibGenAdapter
from research_shared.adapters.scihub import SciHubAdapter
from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter
from research_shared.adapters.base import SourceSearchResult


# ---------------------------------------------------------------------------
# Adapter list for parameterized tests
# ---------------------------------------------------------------------------

ADAPTERS = [
    AnnasArchiveAdapter,
    LibGenAdapter,
    SciHubAdapter,
    InternetArchiveAdapter,
    AcademicTorrentsAdapter,
]

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


class TestTierSpecific:
    """Tests for tier-appropriate behavior."""

    def test_s_tier_adapters_exist(self):
        """Anna's Archive, LibGen, and Sci-Hub are S-tier."""
        s_tier = [
            a for a in ADAPTERS
            if a().tier == "S"
        ]
        s_names = {a().name for a in s_tier}
        assert "annas_archive" in s_names
        assert "libgen" in s_names
        assert "scihub" in s_names

    def test_a_tier_adapters_exist(self):
        """Internet Archive and Academic Torrents are A-tier."""
        a_tier = [
            a for a in ADAPTERS
            if a().tier == "A"
        ]
        a_names = {a().name for a in a_tier}
        assert "internet_archive" in a_names
        assert "academic_torrents" in a_names

    def test_all_adapter_names_unique(self):
        """No two adapters share the same name."""
        names = [cls().name for cls in ADAPTERS]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Adapter-specific
# ---------------------------------------------------------------------------


class TestAnnasArchiveAdapter:
    """Anna's Archive specific tests."""

    async def test_has_algorithmic_trust(self):
        adapter = AnnasArchiveAdapter()
        assert adapter.trust_model == "algorithmic"


class TestLibGenAdapter:
    """LibGen specific tests."""

    async def test_has_community_trust(self):
        adapter = LibGenAdapter()
        assert adapter.trust_model == "community"


class TestSciHubAdapter:
    """Sci-Hub specific tests."""

    async def test_download_url_present_on_resolve(self):
        adapter = SciHubAdapter()
        result = await adapter.resolve_doi("10.1038/test")
        assert result is not None
        assert result.download_url is not None
        assert "sci-hub" in result.download_url
