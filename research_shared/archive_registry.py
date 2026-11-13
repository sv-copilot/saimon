"""archive_registry.py — registry of shadow library source index adapters.

ArchiveRegistry holds all registered adapters and provides lookup,
filtering, and listing.  Adapters are registered at import time
and can be filtered by tier for relevance-weighted search.
"""

from __future__ import annotations

from research_shared.adapters.base import SourceIndexAdapter

# ---------------------------------------------------------------------------
# ArchiveRegistry
# ---------------------------------------------------------------------------


class ArchiveRegistry:
    """A registry of SourceIndexAdapter instances.

    Thread-safe for reads; writes (register) should happen at startup.

    Usage::

        registry = ArchiveRegistry()
        registry.register(AnnasArchiveAdapter())
        adapters = registry.filter(tier="S")
        results = await adapters[0].search("transformer attention", limit=5)
    """

    def __init__(self) -> None:
        self._adapters: dict[str, SourceIndexAdapter] = {}

    # ── registration ──────────────────────────────────────────────

    def register(self, adapter: SourceIndexAdapter) -> None:
        """Register an adapter.  Replaces any existing adapter with the same name."""
        self._adapters[adapter.name] = adapter

    # ── lookup ────────────────────────────────────────────────────

    def get(self, name: str) -> SourceIndexAdapter | None:
        """Return the adapter with *name*, or None."""
        return self._adapters.get(name)

    def list_all(self) -> list[SourceIndexAdapter]:
        """Return all registered adapters, sorted by name."""
        return sorted(self._adapters.values(), key=lambda a: a.name)

    def filter(self, tier: str | None = None) -> list[SourceIndexAdapter]:
        """Return adapters matching *tier* (or all if *tier* is None).

        Results are sorted by name within tier.
        """
        if tier is None:
            return self.list_all()
        return sorted(
            [a for a in self._adapters.values() if a.tier == tier],
            key=lambda a: a.name,
        )

    def list_tiers(self) -> list[str]:
        """Return distinct tiers present in the registry, sorted."""
        return sorted({a.tier for a in self._adapters.values()})

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        return name in self._adapters


# ---------------------------------------------------------------------------
# module-level singleton
# ---------------------------------------------------------------------------

_registry: ArchiveRegistry | None = None


def get_archive_registry() -> ArchiveRegistry:
    """Return the module-level ArchiveRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ArchiveRegistry()
    return _registry


def reset_archive_registry() -> None:
    """Reset the singleton (for tests)."""
    global _registry
    _registry = None
