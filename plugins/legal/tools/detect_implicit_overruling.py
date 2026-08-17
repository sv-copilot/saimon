"""detect_implicit_overruling.py — implicit-overruling detection (#73, tool 3/3).

Flags a green-citator case (every citator treatment is POSITIVE) that briefs
have stopped citing: zero brief citations in the trailing 18-month window.
The 18-month count is read from ``usage["18m"]`` when present, falling back to
``usage["24m"]`` (the widest cumulative window) when the explicit 18-month
window is absent.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plugins.legal.reconcile import POSITIVE, canonical_treatment


def detect_implicit_overruling(
    citation: str,
    citators: dict[str, str],
    usage: dict[str, Any],
) -> dict[str, Any]:
    """Return whether *citation* looks implicitly overruled.

    A case is flagged only when all citator treatments are positive (good law)
    yet no brief has cited it in the trailing 18 months — the classic
    "everyone agrees it's good law, but nobody cites it anymore" signal.
    """
    treatments = {
        source: canonical_treatment(code) for source, code in citators.items()
    }
    green = bool(treatments) and all(t == POSITIVE for t in treatments.values())
    trailing_18m = int(usage.get("18m", usage.get("24m", 0)))
    implicitly_overruled = green and trailing_18m == 0

    if not green:
        reason = (
            f"{citation} is not a green-citator case (treatments are not "
            "uniformly positive)."
        )
    elif trailing_18m == 0:
        reason = (
            f"All citators treat {citation} as good law, but no brief has "
            "cited it in the trailing 18-month window — possible implicit "
            "overruling."
        )
    else:
        reason = (
            f"{citation} is green-citator and still cited in the trailing "
            "18-month window — no implicit overruling."
        )

    return {
        "citation": citation,
        "implicitly_overruled": implicitly_overruled,
        "reason": reason,
    }


class DetectImplicitOverrulingTool:
    """DomainTool wrapper for :func:`detect_implicit_overruling`."""

    name = "legal.detect_implicit_overruling"
    description = (
        "Detect a green-citator case that briefs stopped citing (zero brief "
        "citations in the trailing 18 months)."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "citation": {"type": "string"},
            "citators": {"type": "object"},
            "usage": {"type": "object"},
        },
        "required": ["citation", "citators", "usage"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        citation = arguments.get("citation")
        citators = arguments.get("citators")
        usage = arguments.get("usage")
        if not citation:
            raise ValueError("Parameter 'citation' is required.")
        if not isinstance(citators, dict):
            raise TypeError("Parameter 'citators' must be an object.")
        if not isinstance(usage, dict):
            raise TypeError("Parameter 'usage' must be an object.")
        return detect_implicit_overruling(str(citation), citators, usage)
