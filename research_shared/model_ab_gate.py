"""A/B gate for model-routing changes (SAIMON-MODEL-AB-TEST-1).

Pure functions only: recorded verdicts go in, an allow/deny decision comes out.
No network, no import-time side effects. A saimon route may only flip to a
different (cheaper/free) model once a green offline ``eval.py compare`` for the
affected tier is recorded in ``model_ab_verdict.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Saimon routes governed by the A/B gate, in model-routing config order.
SAIMON_ROUTES = (
    "saimon.generate",
    "saimon.verify",
    "saimon.evaluate",
    "saimon.extract_claims",
)

# The affected eval tier (fixture suite) for each route.
ROUTE_TIERS = {
    "saimon.generate": "generate",
    "saimon.verify": "verify",
    "saimon.evaluate": "evaluate",
    "saimon.extract_claims": "extract_claims",
}

DEFAULT_VERDICT_PATH = Path(__file__).resolve().parents[1] / "model_ab_verdict.json"


@dataclass(frozen=True)
class GateDecision:
    """Outcome of a gate evaluation."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    route: str | None = None
    incumbent: str | None = None
    candidate: str | None = None


def check_model_swap(
    incumbent: str,
    candidate: str,
    verdicts: list[dict],
    route: str | None = None,
) -> GateDecision:
    """Pure gate for a single model swap.

    A swap is allowed when the incumbent and candidate are identical, or when a
    green (``verdict == "OK"``) verdict is recorded for that exact
    incumbent -> candidate pair (and, when ``route`` is given, for that route).
    """
    if incumbent == candidate:
        return GateDecision(
            allowed=True,
            route=route,
            incumbent=incumbent,
            candidate=candidate,
        )

    matching = [
        v
        for v in verdicts
        if v.get("incumbent") == incumbent and v.get("candidate") == candidate
    ]
    if route is not None:
        matching = [v for v in matching if v.get("route") == route]

    if any(v.get("verdict") == "OK" for v in matching):
        return GateDecision(
            allowed=True,
            route=route,
            incumbent=incumbent,
            candidate=candidate,
        )

    if not matching:
        reason = f"no A/B verdict recorded for {incumbent} -> {candidate}"
        if route is not None:
            reason += f" (route {route})"
    else:
        reason = f"A/B verdict for {incumbent} -> {candidate} is not green"
        if route is not None:
            reason += f" (route {route})"
    return GateDecision(
        allowed=False,
        reasons=[reason],
        route=route,
        incumbent=incumbent,
        candidate=candidate,
    )


def gate_routes(
    current_routes: dict[str, str],
    incumbents: dict[str, str],
    verdicts: list[dict],
) -> GateDecision:
    """Gate a full route->model mapping against recorded incumbents.

    ``current_routes`` maps route keys to their currently configured model;
    ``incumbents`` maps route keys to the last green-blessed model. Any route
    whose model changed must carry a green verdict, otherwise the gate denies.
    """
    reasons: list[str] = []
    for route in sorted(current_routes):
        incumbent = incumbents.get(route)
        if incumbent is None:
            continue
        decision = check_model_swap(
            incumbent, current_routes[route], verdicts, route=route
        )
        if not decision.allowed:
            reasons.extend(decision.reasons)
    return GateDecision(allowed=not reasons, reasons=reasons)


def load_verdict_doc(path: str | Path | None = None) -> dict:
    """Load the committed machine-readable A/B verdict document."""
    doc_path = Path(path) if path is not None else DEFAULT_VERDICT_PATH
    return json.loads(doc_path.read_text(encoding="utf-8"))


def load_verdicts(path: str | Path | None = None) -> list[dict]:
    """Return the recorded verdict entries from the verdict document."""
    return load_verdict_doc(path).get("verdicts", [])


def resolve_current_routes() -> dict[str, str]:
    """Resolve each saimon route to its currently configured model."""
    from research_shared import model_routing

    return {route: model_routing.model_for_route(route) for route in SAIMON_ROUTES}


def gate_current_routing(path: str | Path | None = None) -> GateDecision:
    """Gate the committed model routing against the committed verdict document."""
    doc = load_verdict_doc(path)
    return gate_routes(
        resolve_current_routes(),
        doc.get("incumbents", {}),
        doc.get("verdicts", []),
    )
