"""Tests for ArchiveRegistry — adapter registration and lookup."""

import pytest

from research_shared.archive_registry import (
    ArchiveRegistry,
    get_archive_registry,
    reset_archive_registry,
)


# ---------------------------------------------------------------------------
# Fake adapter for tests
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Minimal adapter that satisfies SourceIndexAdapter protocol."""

    def __init__(self, name: str, tier: str, trust_model: str = "community"):
        self.name = name
        self.tier = tier
        self.trust_model = trust_model

    async def search(self, query: str, limit: int = 10, offset: int = 0):
        return []

    async def resolve_doi(self, doi: str):
        return None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestArchiveRegistryRegistration:
    """Tests for registering and retrieving adapters."""

    def test_register_adds_adapter(self):
        """Registering an adapter makes it available via get()."""
        registry = ArchiveRegistry()
        adapter = _FakeAdapter("annas_archive", "S")
        registry.register(adapter)
        assert registry.get("annas_archive") is adapter

    def test_register_replaces_existing(self):
        """Registering with the same name replaces the old adapter."""
        registry = ArchiveRegistry()
        a1 = _FakeAdapter("annas_archive", "S")
        a2 = _FakeAdapter("annas_archive", "A")
        registry.register(a1)
        registry.register(a2)
        assert registry.get("annas_archive") is a2
        assert registry.get("annas_archive").tier == "A"

    def test_get_missing_returns_none(self):
        """Looking up an unregistered adapter returns None."""
        registry = ArchiveRegistry()
        assert registry.get("nonexistent") is None

    def test_contains_works(self):
        """The `in` operator checks for adapter presence."""
        registry = ArchiveRegistry()
        registry.register(_FakeAdapter("libgen", "S"))
        assert "libgen" in registry
        assert "annas_archive" not in registry

    def test_len_counts_adapters(self):
        registry = ArchiveRegistry()
        assert len(registry) == 0
        registry.register(_FakeAdapter("a", "S"))
        registry.register(_FakeAdapter("b", "A"))
        assert len(registry) == 2


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


class TestArchiveRegistryListing:
    """Tests for list_all and filter."""

    @pytest.fixture
    def registry(self) -> ArchiveRegistry:
        r = ArchiveRegistry()
        r.register(_FakeAdapter("annas_archive", "S", "algorithmic"))
        r.register(_FakeAdapter("libgen", "S", "community"))
        r.register(_FakeAdapter("internet_archive", "A", "institutional"))
        r.register(_FakeAdapter("academic_torrents", "A", "community"))
        r.register(_FakeAdapter("memory_of_world", "B", "community"))
        return r

    def test_list_all_returns_all_sorted(self, registry):
        """list_all returns all adapters sorted by name."""
        adapters = registry.list_all()
        names = [a.name for a in adapters]
        assert names == [
            "academic_torrents",
            "annas_archive",
            "internet_archive",
            "libgen",
            "memory_of_world",
        ]

    def test_filter_by_tier_s(self, registry):
        """Filtering by tier 'S' returns only S-tier adapters."""
        adapters = registry.filter(tier="S")
        names = [a.name for a in adapters]
        assert names == ["annas_archive", "libgen"]

    def test_filter_by_tier_a(self, registry):
        """Filtering by tier 'A' returns only A-tier adapters."""
        adapters = registry.filter(tier="A")
        names = [a.name for a in adapters]
        assert names == ["academic_torrents", "internet_archive"]

    def test_filter_by_tier_none_returns_all(self, registry):
        """Filtering with tier=None returns all adapters."""
        adapters = registry.filter(tier=None)
        assert len(adapters) == 5

    def test_filter_empty_tier_returns_empty(self, registry):
        """Filtering by a tier with no adapters returns empty list."""
        assert registry.filter(tier="C") == []

    def test_list_tiers_returns_distinct_sorted(self, registry):
        """list_tiers returns distinct tiers sorted."""
        tiers = registry.list_tiers()
        assert tiers == ["A", "B", "S"]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestArchiveRegistrySingleton:
    """Tests for the module-level singleton."""

    def test_get_returns_same_instance(self):
        """get_archive_registry returns the same instance on repeated calls."""
        reset_archive_registry()
        r1 = get_archive_registry()
        r2 = get_archive_registry()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        """reset_archive_registry clears the singleton."""
        r1 = get_archive_registry()
        r1.register(_FakeAdapter("test", "S"))
        reset_archive_registry()
        r2 = get_archive_registry()
        assert r1 is not r2
        assert len(r2) == 0
