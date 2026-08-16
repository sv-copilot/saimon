"""plugins.legal — the legal research domain plugin (retail).

First slice on the retail side of the licensing boundary.  Ships the citation
graph schema (an optional ``legal_cases`` migration) plus citation-edge
conventions over the domain-agnostic knowledge graph.  Adapters and content
types arrive in SAIMON-LEGAL-ADAPTERS-1 (#72).
"""

from __future__ import annotations

from typing import Any

from plugins.legal.adapters import (
    CaselawAccessAdapter,
    CourtListenerAdapter,
    RecapAdapter,
    ScotusMeritsAdapter,
)
from plugins.legal.content_types import CONTENT_TYPES as LEGAL_CONTENT_TYPES
from plugins.legal.migrations import list_migrations
from plugins.legal.weighting import persuasive_authority
from research_shared.domain_plugin import DomainPlugin


def schema_migrations() -> list[str]:
    """Return migration file paths shipped by this plugin."""
    return list_migrations()


class LegalPlugin(DomainPlugin):
    """The legal research plugin.

    Domain data lives behind the plugin boundary: citation edges use a
    namespaced relation type over ``knowledge_graph_edges`` and case nodes use
    ``content_type = 'legal:case'``.  No core schema changes.
    """

    domain = "legal"

    def adapters(self) -> list[Any]:
        return [
            CourtListenerAdapter(),
            RecapAdapter(),
            CaselawAccessAdapter(),
            ScotusMeritsAdapter(),
        ]

    def content_types(self) -> list[dict[str, Any]]:
        return LEGAL_CONTENT_TYPES

    def tools(self) -> list[Any]:
        # Legal tools arrive in #73-#75.
        return []

    def schema_migrations(self) -> list[str]:
        return schema_migrations()

    def weighting_models(self) -> dict[str, Any]:
        return {"persuasive_authority": persuasive_authority}

    def readiness(self) -> dict[str, Any]:
        """Aggregate adapter readiness for the domain-mcp onboard helper."""
        statuses = [a.readiness() for a in self.adapters()]
        missing = [s for s in statuses if s.get("status") == "missing_config"]
        if missing:
            return {
                "status": "missing_config",
                "details": "; ".join(s["details"] for s in missing),
            }
        return {
            "status": "ready",
            "details": f"{len(statuses)} legal adapters configured",
        }


PLUGIN = LegalPlugin()
