"""usage_layer.py — opinion-vs-brief usage layer (legal tool 10/10, #75).

Composes search: compare how often each authority is cited in judicial
opinions versus live briefs, and surface authorities that opinions rely on but
litigators avoid.  Deterministic — no network I/O.
"""

from __future__ import annotations

from typing import Any, ClassVar


def _nonnegative_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def build_usage_layer(authorities: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the opinion-vs-brief citation delta per authority.

    ``avoided`` authorities are those cited in at least one opinion but in no
    brief — the cases litigators are not reaching for.  ``brief_only``
    authorities are cited in briefs but absent from the opinion graph.
    """
    rows: list[dict[str, Any]] = []
    avoided: list[str] = []
    total_brief = 0
    total_opinion = 0
    brief_only_count = 0

    for authority in authorities:
        if not isinstance(authority, dict):
            continue
        citation = str(authority.get("citation", "")).strip() or "unnamed"
        brief = _nonnegative_int(authority.get("brief_citations"))
        opinion = _nonnegative_int(authority.get("opinion_citations"))
        delta = opinion - brief
        is_avoided = opinion > 0 and brief == 0
        is_brief_only = brief > 0 and opinion == 0

        total_brief += brief
        total_opinion += opinion
        brief_only_count += 1 if is_brief_only else 0
        if is_avoided:
            avoided.append(citation)

        rows.append(
            {
                "citation": citation,
                "brief_citations": brief,
                "opinion_citations": opinion,
                "delta": delta,
                "avoided": is_avoided,
                "brief_only": is_brief_only,
            }
        )

    avoided_count = len(avoided)
    noun = "authority" if avoided_count == 1 else "authorities"
    headline = f"{avoided_count} {noun} avoided by litigators"

    memo = (
        f"{headline}. {total_brief} brief citations vs {total_opinion} "
        f"opinion citations; {brief_only_count} "
        f"{'authority' if brief_only_count == 1 else 'authorities'} cited in "
        "briefs but absent from the opinion graph."
    )

    return {
        "headline": headline,
        "avoided_count": avoided_count,
        "avoided": avoided,
        "rows": rows,
        "stats": {
            "total_brief_citations": total_brief,
            "total_opinion_citations": total_opinion,
            "total_delta": total_opinion - total_brief,
            "brief_only_count": brief_only_count,
        },
        "memo": memo,
    }


class BuildUsageLayerTool:
    """DomainTool wrapper for :func:`build_usage_layer`."""

    name = "legal.build_usage_layer"
    description = (
        "Compute the opinion-vs-brief citation delta per authority, surfacing "
        "authorities that opinions rely on but litigators avoid."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "authorities": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["authorities"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        authorities = arguments.get("authorities")
        if not isinstance(authorities, list):
            raise TypeError("Parameter 'authorities' must be a list.")
        return build_usage_layer(authorities)
