"""plugins.legal.tools — the legal domain tools (slices #73-#75).

Each tool is a thin ``DomainTool`` wrapper over pure, deterministic logic.
The tools compose the core MCP primitives and the legal building blocks
(reconciliation engine, weighting model, adapters) — they never reimplement
them.
"""

from __future__ import annotations

from plugins.legal.tools.authority_ladder import (
    BuildAuthorityLadderTool,
    build_authority_ladder,
)
from plugins.legal.tools.detect_implicit_overruling import (
    DetectImplicitOverrulingTool,
    detect_implicit_overruling,
)
from plugins.legal.tools.doctrine_diffusion import (
    MapDoctrineDiffusionTool,
    map_doctrine_diffusion,
)
from plugins.legal.tools.erie_guess import PredictErieGuessTool, predict_erie_guess
from plugins.legal.tools.parse_citation import ParseCitationTool, parse_citation
from plugins.legal.tools.procedural_history import (
    ExtractProceduralHistoryTool,
    extract_procedural_history,
)
from plugins.legal.tools.rank_authority import (
    RankAuthorityTool,
    rank_persuasive_authority,
)
from plugins.legal.tools.reconcile_citators import (
    ReconcileCitatorsTool,
    reconcile_citators,
)
from plugins.legal.tools.split_of_authority import (
    DetectSplitOfAuthorityTool,
    detect_split_of_authority,
)
from plugins.legal.tools.usage_layer import BuildUsageLayerTool, build_usage_layer

__all__ = [
    "BuildAuthorityLadderTool",
    "BuildUsageLayerTool",
    "DetectImplicitOverrulingTool",
    "DetectSplitOfAuthorityTool",
    "ExtractProceduralHistoryTool",
    "MapDoctrineDiffusionTool",
    "ParseCitationTool",
    "PredictErieGuessTool",
    "RankAuthorityTool",
    "ReconcileCitatorsTool",
    "build_authority_ladder",
    "build_usage_layer",
    "detect_implicit_overruling",
    "detect_split_of_authority",
    "extract_procedural_history",
    "map_doctrine_diffusion",
    "parse_citation",
    "predict_erie_guess",
    "rank_persuasive_authority",
    "reconcile_citators",
]
