"""split_of_authority.py — circuit-split detection tool (legal tool 6/6, #74).

Groups cases by circuit and reports each circuit's position(s) on a legal
question, flagging a split of authority when circuits disagree.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

_ORDINALS = (
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
)
_CIRCUIT_RE = re.compile(r"(?:" + "|".join(_ORDINALS) + r"|d\.c\.|federal)\s+circuit")


def _circuit_of(court: str) -> str:
    c = (court or "").lower()
    match = _CIRCUIT_RE.search(c)
    if match:
        return match.group(0).title()
    if "supreme" in c:
        return "Supreme Court"
    return (court or "").strip() or "unknown"


def detect_split_of_authority(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Group cases by circuit and report positions per circuit + split flag."""
    grouped: dict[str, dict[str, Any]] = {}
    for case in cases:
        meta = case.get("metadata", {}) if isinstance(case, dict) else {}
        circuit = _circuit_of(str(meta.get("court", "")))
        position = (meta.get("position") or "").strip().lower() or "undecided"
        entry = grouped.setdefault(circuit, {"positions": set(), "case_count": 0})
        entry["positions"].add(position)
        entry["case_count"] += 1

    circuits = {
        circuit: {
            "positions": sorted(info["positions"]),
            "case_count": info["case_count"],
        }
        for circuit, info in sorted(grouped.items())
    }

    positions_across = {
        position for info in circuits.values() for position in info["positions"]
    }
    split = len(positions_across) > 1

    if split:
        summary = (
            "Circuits disagree: "
            + "; ".join(
                f"{circuit} holds {', '.join(info['positions'])}"
                for circuit, info in circuits.items()
            )
            + "."
        )
    else:
        summary = "No split of authority detected."

    return {"circuits": circuits, "split": split, "summary": summary}


class DetectSplitOfAuthorityTool:
    """DomainTool wrapper for :func:`detect_split_of_authority`."""

    name = "legal.detect_split_of_authority"
    description = (
        "Report each circuit's position on a legal question and flag a split "
        "of authority when circuits disagree."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "cases": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["cases"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        cases = arguments.get("cases")
        if not isinstance(cases, list):
            raise TypeError("Parameter 'cases' must be a list.")
        return detect_split_of_authority(cases)
