"""domain_plugin.py — the domain plugin contract.

Saimon's six core MCPs are domain-agnostic.  All domain-specific logic lives
behind a plugin boundary.  This module defines the open-source (MIT) interface
every domain plugin implements against:

- ``DomainTool`` — a runtime-checkable structural protocol for a single tool.
- ``DomainPlugin`` — an ABC for a full plugin (adapters, content types, tools).

The interface itself is intentionally domain-agnostic: it must not import or
reference any specific domain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DomainTool(Protocol):
    """Structural protocol for a single domain tool.

    Any object exposing the four members below *is* a ``DomainTool`` — no
    subclassing required.  Because the protocol is ``runtime_checkable``,
    ``isinstance``/``issubclass`` checks succeed against conforming objects.

    The data members are declared as methods (rather than bare annotations)
    so the protocol has only callable members, which CPython requires for
    ``issubclass()`` support.  Implementations may satisfy them with plain
    attributes or methods.
    """

    def name(self) -> str:
        """Stable machine-readable tool name."""
        ...

    def description(self) -> str:
        """Human-readable one-line description of the tool."""
        ...

    def input_schema(self) -> dict[str, Any]:
        """JSON Schema describing the tool's ``arguments``."""
        ...

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool against ``arguments`` and return a result dict."""
        ...


class DomainPlugin(ABC):
    """Abstract base class for a domain plugin.

    Subclasses must implement the abstract members (``domain``, ``adapters()``,
    ``content_types()``, ``tools()``).  The optional members
    (``schema_migrations()``, ``weighting_models()``) default to empty
    collections and need not be overridden.
    """

    @property
    @abstractmethod
    def domain(self) -> str:
        """Machine-readable domain name (e.g. ``"example"``)."""
        raise NotImplementedError

    @abstractmethod
    def adapters(self) -> list[Any]:
        """Return the source adapters this plugin registers."""
        raise NotImplementedError

    @abstractmethod
    def content_types(self) -> list[dict[str, Any]]:
        """Return the content type definitions this plugin registers."""
        raise NotImplementedError

    @abstractmethod
    def tools(self) -> list[DomainTool]:
        """Return the domain tools this plugin exposes."""
        raise NotImplementedError

    def schema_migrations(self) -> list[Any]:
        """Return schema migrations this plugin ships (default: none)."""
        return []

    def weighting_models(self) -> dict[str, Any]:
        """Return weighting models this plugin ships (default: none)."""
        return {}
