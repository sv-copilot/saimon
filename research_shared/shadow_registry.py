"""shadow_registry.py — private compatibility shim.

The registry *mechanism* now lives in :mod:`research_shared.source_registry`, and
which sources this deployment registers lives in :mod:`research_shared.sources`.
This module keeps the previous names working for this deployment's own code and
tests while they are migrated; it is deliberately not part of the public
artifact.

New code imports from :mod:`research_shared.source_registry`.
"""

from __future__ import annotations

from research_shared.source_registry import (
    SourceRegistry,
    get_registry,
    reset_registry,
)

#: Previous name for the same class.
ShadowRegistry = SourceRegistry


def get_shadow_registry() -> SourceRegistry:
    """Previous name for :func:`research_shared.source_registry.get_registry`."""
    return get_registry()


def reset_shadow_registry() -> None:
    """Previous name for :func:`research_shared.source_registry.reset_registry`."""
    reset_registry()


__all__ = [
    "ShadowRegistry",
    "SourceRegistry",
    "get_registry",
    "get_shadow_registry",
    "reset_registry",
    "reset_shadow_registry",
]
