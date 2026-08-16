"""authority_ladder.py — authority ladder tool (legal tool 5/6, #74).

Ranks candidate authorities strongest-first using the #71 weighting model and
emits an ordered ladder with reasoning.  The "generate" step is a
deterministic memo (the domain plugin has no LLM).
"""

from __future__ import annotations

from typing import Any, ClassVar

from plugins.legal.weighting import persuasive_authority_breakdown


def _citation_of(case: dict[str, Any]) -> str:
    meta = case.get("metadata", {}) if isinstance(case, dict) else {}
    return (
        meta.get("citation_string")
        or case.get("title")
        or case.get("id")
        or "unnamed case"
    )


def _reasoning(breakdown: dict[str, Any]) -> str:
    parts = [
        f"{f['factor']} {f['value']:.2f}×{f['weight']:.2f}"
        for f in breakdown["breakdown"]
    ]
    return f"persuasive authority {breakdown['score']:.2f} = " + " + ".join(parts)


def build_authority_ladder(
    candidates: list[dict[str, Any]], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Rank candidate authorities strongest-first, with reasoning + memo."""
    ranked = []
    for case in candidates:
        breakdown = persuasive_authority_breakdown(case, context)
        ranked.append(
            {
                "citation": _citation_of(case),
                "score": round(breakdown["score"], 4),
                "reasoning": _reasoning(breakdown),
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)

    if not ranked:
        memo = "No candidate authorities to rank."
    else:
        memo = (
            f"Strongest authority: {ranked[0]['citation']} "
            f"(score {ranked[0]['score']:.2f})."
        )
    return {"ladder": ranked, "memo": memo}


class BuildAuthorityLadderTool:
    """DomainTool wrapper for :func:`build_authority_ladder`."""

    name = "legal.build_authority_ladder"
    description = (
        "Rank candidate authorities strongest-first by persuasive authority, "
        "with reasoning and an ordered ladder memo."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "candidates": {"type": "array", "items": {"type": "object"}},
            "context": {"type": "object"},
        },
        "required": ["candidates"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        candidates = arguments.get("candidates")
        if not isinstance(candidates, list):
            raise TypeError("Parameter 'candidates' must be a list.")
        context = arguments.get("context") or {}
        if not isinstance(context, dict):
            raise TypeError("Parameter 'context' must be an object.")
        return build_authority_ladder(candidates, context)
