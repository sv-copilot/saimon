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
from plugins.legal.tools.parse_citation import ParseCitationTool, parse_citation
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

__all__ = [
    "BuildAuthorityLadderTool",
    "DetectImplicitOverrulingTool",
    "DetectSplitOfAuthorityTool",
    "ParseCitationTool",
    "RankAuthorityTool",
    "ReconcileCitatorsTool",
    "build_authority_ladder",
    "detect_implicit_overruling",
    "detect_split_of_authority",
    "parse_citation",
    "rank_persuasive_authority",
    "reconcile_citators",
]
