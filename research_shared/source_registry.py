"""source_registry.py — registry of source index adapters.

A `SourceRegistry` holds the adapters a deployment has decided to search and
provides lookup, filtering and listing over them. Adapters register at
composition time (see `research_shared.sources`), never by being named inside a
service, so a deployment chooses its sources in one place.

Adapters are filtered by `tier`, which is the adapter's own declaration of how
much weight its results deserve in relevance ranking. The vocabulary is open:
`filter(tier="S")` returns the adapters that declared themselves tier S.

An adapter may also declare, optionally:

- `label` — the human-readable name shown to callers (defaults to `name`)
- `kind`  — what it serves: ``"paper"``, ``"book"``, ``"dataset"``, ``"mixed"``
- `access` — ``"anonymous"``, ``"credentialed"``, ``"institutional"`` or ``"local"``:
  what a caller must supply to reach the source, so nothing is implied about
  anything else

None of those are required: the helpers below fall back to the adapter's `name`
and to ``"mixed"`` / ``"anonymous"``. Read them through the helpers rather than off
the adapter, so an adapter that declares nothing still works.
"""

from __future__ import annotations

from research_shared.adapters.base import SourceIndexAdapter


class SourceRegistry:
    """A registry of SourceIndexAdapter instances.

    Thread-safe for reads; writes (register) happen at composition time.

    Usage::

        registry = SourceRegistry()
        registry.register(MySourceAdapter())
        for adapter in registry.filter(tier="A"):
            results = await adapter.search("transformer attention", limit=5)
    """

    def __init__(self) -> None:
        self._adapters: dict[str, SourceIndexAdapter] = {}

    # ── registration ──────────────────────────────────────────────

    def register(self, adapter: SourceIndexAdapter) -> None:
        """Register an adapter. Replaces any existing adapter with the same name."""
        self._adapters[adapter.name] = adapter

    def register_all(self, adapters: list[SourceIndexAdapter]) -> None:
        """Register several adapters in one call."""
        for adapter in adapters:
            self.register(adapter)

    # ── lookup ────────────────────────────────────────────────────

    def get(self, name: str) -> SourceIndexAdapter | None:
        """Return the adapter with *name*, or None."""
        return self._adapters.get(name)

    def list_all(self) -> list[SourceIndexAdapter]:
        """Return all registered adapters, sorted by name."""
        return sorted(self._adapters.values(), key=lambda a: a.name)

    def select(self, names: list[str] | None = None) -> list[SourceIndexAdapter]:
        """Return the named adapters, or every adapter when *names* is None.

        Unknown names are ignored rather than raising: a caller that asks for a
        source this deployment has not registered gets the rest, not an error.
        """
        if names is None:
            return self.list_all()
        want = set(names)
        return [a for a in self.list_all() if a.name in want]

    def filter(self, tier: str | None = None) -> list[SourceIndexAdapter]:
        """Return adapters matching *tier* (or all if *tier* is None)."""
        if tier is None:
            return self.list_all()
        return sorted(
            [a for a in self._adapters.values() if a.tier == tier],
            key=lambda a: a.name,
        )

    def filter_by_kind(self, kind: str | None = None) -> list[SourceIndexAdapter]:
        """Return adapters serving *kind* (or all if *kind* is None)."""
        if kind is None:
            return self.list_all()
        return [a for a in self.list_all() if adapter_kind(a) == kind]

    def list_tiers(self) -> list[str]:
        """Return distinct tiers present in the registry, sorted."""
        return sorted({a.tier for a in self._adapters.values()})

    def list_names(self) -> list[str]:
        """Return the registered adapter names, sorted."""
        return sorted(self._adapters)

    def labels(self) -> dict[str, str]:
        """Map adapter name to its display label."""
        return {a.name: adapter_label(a) for a in self.list_all()}

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        return name in self._adapters


# ---------------------------------------------------------------------------
# optional-attribute helpers
# ---------------------------------------------------------------------------


def adapter_label(adapter: SourceIndexAdapter) -> str:
    """Display label for *adapter*, defaulting to its name."""
    return getattr(adapter, "label", None) or adapter.name


def adapter_kind(adapter: SourceIndexAdapter) -> str:
    """What *adapter* serves, defaulting to ``"mixed"``."""
    return getattr(adapter, "kind", None) or "mixed"


def adapter_access(adapter: SourceIndexAdapter) -> str:
    """What *adapter* requires to be reached, defaulting to ``"anonymous"``."""
    return getattr(adapter, "access", None) or "anonymous"


# ---------------------------------------------------------------------------
# module-level singleton
# ---------------------------------------------------------------------------

_registry: SourceRegistry | None = None


def get_registry() -> SourceRegistry:
    """Return the module-level SourceRegistry singleton, composing it once."""
    global _registry
    if _registry is None:
        _registry = SourceRegistry()
        # Imported here rather than at module scope: the composition module
        # imports adapter implementations, which import this module's types.
        from research_shared.sources import compose_registry

        compose_registry(_registry)
    return _registry


def reset_registry() -> None:
    """Reset the singleton (for tests)."""
    global _registry
    _registry = None
