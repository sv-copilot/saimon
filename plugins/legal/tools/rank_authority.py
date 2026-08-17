"""rank_authority.py — persuasive-authority ranking tool (legal tool 4/6, #74).

Composes the #71 weighting model: score a case in a target jurisdiction and
return the 0..1 score plus the five-factor breakdown.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plugins.legal.weighting import persuasive_authority_breakdown


def rank_persuasive_authority(
    case: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Score *case*'s persuasive authority in the target jurisdiction."""
    breakdown = persuasive_authority_breakdown(case, context)
    return {
        "score": round(breakdown["score"], 4),
        "breakdown": breakdown["breakdown"],
    }


class RankAuthorityTool:
    """DomainTool wrapper for :func:`rank_persuasive_authority`."""

    name = "legal.rank_persuasive_authority"
    description = (
        "Score a case's persuasive authority in a target jurisdiction, "
        "returning a 0..1 score and a five-factor breakdown."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "case": {"type": "object"},
            "context": {"type": "object"},
        },
        "required": ["case"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        case = arguments.get("case")
        if not isinstance(case, dict):
            raise TypeError("Parameter 'case' must be an object.")
        context = arguments.get("context") or {}
        if not isinstance(context, dict):
            raise TypeError("Parameter 'context' must be an object.")
        return rank_persuasive_authority(case, context)
