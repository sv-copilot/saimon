"""plugins.legal — the legal research domain plugin (retail).

First slice on the retail side of the licensing boundary.  Ships the citation
graph schema (an optional ``legal_cases`` migration) plus citation-edge
conventions over the domain-agnostic knowledge graph.  Adapters and content
types arrive in SAIMON-LEGAL-ADAPTERS-1 (#72).
"""

from __future__ import annotations

from typing import Any

from plugins.legal.migrations import list_migrations
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
        # Adapters register in SAIMON-LEGAL-ADAPTERS-1 (#72).
        return []

    def content_types(self) -> list[dict[str, Any]]:
        # Content types register in SAIMON-LEGAL-ADAPTERS-1 (#72).
        return []

    def tools(self) -> list[Any]:
        # Legal tools arrive in #73-#75.
        return []

    def schema_migrations(self) -> list[str]:
        return schema_migrations()


PLUGIN = LegalPlugin()
