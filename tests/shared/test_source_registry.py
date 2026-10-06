"""Tests for SourceRegistry — the generic adapter registry and its helpers.

These are the guarantees the shared code relies on: services ask the registry for
adapters, so registration, lookup, selection and the optional-attribute helpers
have to behave the same for every deployment and for an adapter that declares
nothing but the required protocol members.
"""

import pytest

from research_shared.source_registry import (
    SourceRegistry,
    adapter_access,
    adapter_kind,
    adapter_label,
    get_registry,
    reset_registry,
)


class _BareAdapter:
    """An adapter that declares only the required protocol members."""

    def __init__(self, name: str, tier: str = "A", trust_model: str = "community"):
        self.name = name
        self.tier = tier
        self.trust_model = trust_model

    async def search(self, query: str, limit: int = 10, offset: int = 0):
        return []

    async def resolve_doi(self, doi: str):
        return None

    async def fetch_fulltext(self, result):
        return None


class _RichAdapter(_BareAdapter):
    """An adapter that declares the optional metadata too."""

    def __init__(self, name: str, **kw):
        super().__init__(name, **kw)
        self.label = "Rich Source"
        self.kind = "dataset"
        self.access = "credentialed"


# ---------------------------------------------------------------------------
# mechanism
# ---------------------------------------------------------------------------


class TestRegistryMechanism:
    def test_a_bare_registry_is_empty(self):
        """Nothing is registered until something registers it."""
        assert len(SourceRegistry()) == 0

    def test_register_then_get(self):
        registry = SourceRegistry()
        adapter = _BareAdapter("alpha")
        registry.register(adapter)
        assert registry.get("alpha") is adapter
        assert "alpha" in registry

    def test_register_replaces_by_name(self):
        registry = SourceRegistry()
        registry.register(_BareAdapter("alpha", tier="S"))
        replacement = _BareAdapter("alpha", tier="C")
        registry.register(replacement)
        assert registry.get("alpha") is replacement
        assert len(registry) == 1

    def test_register_all_registers_each(self):
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("alpha"), _BareAdapter("beta")])
        assert registry.list_names() == ["alpha", "beta"]

    def test_get_missing_returns_none(self):
        assert SourceRegistry().get("nope") is None

    def test_list_all_is_sorted_by_name(self):
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("gamma"), _BareAdapter("alpha")])
        assert [a.name for a in registry.list_all()] == ["alpha", "gamma"]

    def test_filter_by_tier(self):
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("alpha", "S"), _BareAdapter("beta", "A")])
        assert [a.name for a in registry.filter(tier="S")] == ["alpha"]
        assert [a.name for a in registry.filter()] == ["alpha", "beta"]
        assert registry.list_tiers() == ["A", "S"]


# ---------------------------------------------------------------------------
# selection — how a service asks for sources
# ---------------------------------------------------------------------------


class TestSelection:
    def test_select_none_returns_everything(self):
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("alpha"), _BareAdapter("beta")])
        assert [a.name for a in registry.select(None)] == ["alpha", "beta"]

    def test_select_narrows_to_the_named_sources(self):
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("alpha"), _BareAdapter("beta")])
        assert [a.name for a in registry.select(["beta"])] == ["beta"]

    def test_select_ignores_unknown_names(self):
        """A caller asking for a source this deployment lacks gets the rest.

        Raising here would turn a configuration difference into an outage.
        """
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("alpha")])
        assert [a.name for a in registry.select(["alpha", "not_registered"])] == ["alpha"]
        assert registry.select(["not_registered"]) == []

    def test_select_preserves_registry_order(self):
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("alpha"), _BareAdapter("beta")])
        assert [a.name for a in registry.select(["beta", "alpha"])] == ["alpha", "beta"]

    def test_filter_by_kind_uses_the_declared_kind(self):
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("alpha"), _RichAdapter("beta")])
        assert [a.name for a in registry.filter_by_kind("dataset")] == ["beta"]
        assert [a.name for a in registry.filter_by_kind()] == ["alpha", "beta"]

    def test_labels_map_name_to_declared_label(self):
        registry = SourceRegistry()
        registry.register_all([_BareAdapter("alpha"), _RichAdapter("beta")])
        assert registry.labels() == {"alpha": "alpha", "beta": "Rich Source"}


# ---------------------------------------------------------------------------
# optional metadata helpers
# ---------------------------------------------------------------------------


class TestOptionalMetadataHelpers:
    def test_defaults_when_nothing_is_declared(self):
        """An adapter that declares no metadata still describes itself."""
        bare = _BareAdapter("alpha")
        assert adapter_label(bare) == "alpha"
        assert adapter_kind(bare) == "mixed"
        assert adapter_access(bare) == "anonymous"

    def test_declared_values_win(self):
        rich = _RichAdapter("beta")
        assert adapter_label(rich) == "Rich Source"
        assert adapter_kind(rich) == "dataset"
        assert adapter_access(rich) == "credentialed"

    def test_empty_string_falls_back_to_the_default(self):
        """A blank declaration is treated as no declaration."""
        class Blank(_BareAdapter):
            label = ""
            kind = ""
            access = ""

        blank = Blank("gamma")
        assert adapter_label(blank) == "gamma"
        assert adapter_kind(blank) == "mixed"
        assert adapter_access(blank) == "anonymous"


# ---------------------------------------------------------------------------
# the composition point
# ---------------------------------------------------------------------------


class TestComposition:
    def test_singleton_is_composed_on_first_use(self):
        reset_registry()
        registry = get_registry()
        assert len(registry) > 0, "the composition point registered nothing"

    def test_singleton_is_stable(self):
        reset_registry()
        assert get_registry() is get_registry()

    def test_composed_defaults_are_registered(self):
        """Every source a default query uses must exist in the registry.

        Otherwise a query with no explicit source list would silently search
        nothing.
        """
        from research_shared.sources import default_source_indexes

        reset_registry()
        registry = get_registry()
        missing = sorted(default_source_indexes() - set(registry.list_names()))
        assert not missing, f"default sources not registered: {missing}"

    def test_reset_clears_registration_from_the_previous_instance(self):
        reset_registry()
        registry = get_registry()
        registry.register(_BareAdapter("scratch"))
        reset_registry()
        assert "scratch" not in get_registry()
