"""reconcile_citators.py — citator reconciliation tool (legal tool 2/3, #73).

Composes the #70 reconciliation engine: canonicalize citator treatments,
detect disagreements, build the brief-usage signal, and classify the case into
one of six canonical states.  The domain plugin has no LLM, so the "research
memo" is a deterministic, templated summary over the classification result.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plugins.legal.reconcile import Classification, build_usage_signal, classify


def _memo(citation: str, result: Classification) -> str:
    return (
        f"{citation}: citator consensus is {result.consensus}; classified "
        f"{result.state} ({result.rationale})."
    )


def reconcile_citators(
    citation: str,
    citators: dict[str, str],
    usage: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile citator treatments for a citation.

    Returns consensus, disagreements, usage signal, classification state, and
    a deterministic research memo.
    """
    signal = build_usage_signal(usage)
    result = classify(citators, signal)
    disagreements = [
        {
            "source_a": d.source_a,
            "source_b": d.source_b,
            "treatment_a": d.treatment_a,
            "treatment_b": d.treatment_b,
        }
        for d in result.disagreements
    ]
    return {
        "citation": citation,
        "consensus": result.consensus,
        "classification": result.state,
        "disagreements": disagreements,
        "usage_signal": signal,
        "memo": _memo(citation, result),
    }


class ReconcileCitatorsTool:
    """DomainTool wrapper for :func:`reconcile_citators`."""

    name = "legal.reconcile_citators"
    description = (
        "Reconcile citator treatments for a citation into consensus, "
        "disagreements, a brief-usage signal, and a six-state classification."
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
        return reconcile_citators(str(citation), citators, usage)
