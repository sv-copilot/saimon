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
from plugins.legal.tools.authority_ladder import BuildAuthorityLadderTool
from plugins.legal.tools.detect_implicit_overruling import (
    DetectImplicitOverrulingTool,
)
from plugins.legal.tools.doctrine_diffusion import MapDoctrineDiffusionTool
from plugins.legal.tools.erie_guess import PredictErieGuessTool
from plugins.legal.tools.parse_citation import ParseCitationTool
from plugins.legal.tools.procedural_history import ExtractProceduralHistoryTool
from plugins.legal.tools.rank_authority import RankAuthorityTool
from plugins.legal.tools.reconcile_citators import ReconcileCitatorsTool
from plugins.legal.tools.split_of_authority import DetectSplitOfAuthorityTool
from plugins.legal.tools.usage_layer import BuildUsageLayerTool
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
        # Legal tools 1-3 arrive in SAIMON-LEGAL-TOOLS-CORE-1 (#73);
        # tools 4-6 arrive in SAIMON-LEGAL-TOOLS-AUTH-1 (#74); tools 7-10
        # arrive in SAIMON-LEGAL-TOOLS-USAGE-1 (#75).
        return [
            ParseCitationTool(),
            ReconcileCitatorsTool(),
            DetectImplicitOverrulingTool(),
            RankAuthorityTool(),
            BuildAuthorityLadderTool(),
            DetectSplitOfAuthorityTool(),
            MapDoctrineDiffusionTool(),
            PredictErieGuessTool(),
            ExtractProceduralHistoryTool(),
            BuildUsageLayerTool(),
        ]

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
