"""Tests for ShadowRegistry — adapter registration and lookup."""

import pytest

from research_shared.shadow_registry import (
    ShadowRegistry,
    get_shadow_registry,
    reset_shadow_registry,
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


class TestShadowRegistryRegistration:
    """Tests for registering and retrieving adapters."""

    def test_register_adds_adapter(self):
        """Registering an adapter makes it available via get()."""
        registry = ShadowRegistry()
        adapter = _FakeAdapter("annas_archive", "S")
        registry.register(adapter)
        assert registry.get("annas_archive") is adapter

    def test_register_replaces_existing(self):
        """Registering with the same name replaces the old adapter."""
        registry = ShadowRegistry()
        a1 = _FakeAdapter("annas_archive", "S")
        a2 = _FakeAdapter("annas_archive", "A")
        registry.register(a1)
        registry.register(a2)
        assert registry.get("annas_archive") is a2
        assert registry.get("annas_archive").tier == "A"

    def test_get_missing_returns_none(self):
        """Looking up an unregistered adapter returns None."""
        registry = ShadowRegistry()
        assert registry.get("nonexistent") is None

    def test_contains_works(self):
        """The `in` operator checks for adapter presence."""
        registry = ShadowRegistry()
        registry.register(_FakeAdapter("libgen", "S"))
        assert "libgen" in registry
        assert "annas_archive" not in registry

    def test_len_counts_adapters(self):
        registry = ShadowRegistry()
        assert len(registry) == 0
        registry.register(_FakeAdapter("a", "S"))
        registry.register(_FakeAdapter("b", "A"))
        assert len(registry) == 2


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


class TestShadowRegistryListing:
    """Tests for list_all and filter."""

    @pytest.fixture
    def registry(self) -> ShadowRegistry:
        r = ShadowRegistry()
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


class TestShadowRegistrySingleton:
    """Tests for the module-level singleton."""

    def test_get_returns_same_instance(self):
        """get_shadow_registry returns the same instance on repeated calls."""
        reset_shadow_registry()
        r1 = get_shadow_registry()
        r2 = get_shadow_registry()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        """reset_shadow_registry clears the singleton; a fresh one re-composes.

        The contract changed with the composition point: a registry obtained from
        the singleton is now the deployment's composed source set, rather than an
        empty object that callers populate themselves. What reset must still
        guarantee is that no state leaks across a reset.
        """
        r1 = get_shadow_registry()
        r1.register(_FakeAdapter("test", "S"))
        reset_shadow_registry()
        r2 = get_shadow_registry()
        assert r1 is not r2
        assert "test" not in r2
        assert len(r2) > 0  # composed from this deployment's source set
        # The mechanism is unchanged: a bare registry starts empty.
        assert len(ShadowRegistry()) == 0
