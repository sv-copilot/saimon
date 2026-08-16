"""plugins.legal.tools — the legal domain tools (slices #73-#75).

Each tool is a thin ``DomainTool`` wrapper over pure, deterministic logic.
The tools compose the core MCP primitives and the legal building blocks
(reconciliation engine, weighting model, adapters) — they never reimplement
them.
"""

from __future__ import annotations

from plugins.legal.tools.detect_implicit_overruling import (
    DetectImplicitOverrulingTool,
    detect_implicit_overruling,
)
from plugins.legal.tools.parse_citation import ParseCitationTool, parse_citation
from plugins.legal.tools.reconcile_citators import (
    ReconcileCitatorsTool,
    reconcile_citators,
)

__all__ = [
    "DetectImplicitOverrulingTool",
    "ParseCitationTool",
    "ReconcileCitatorsTool",
    "detect_implicit_overruling",
    "parse_citation",
    "reconcile_citators",
]
