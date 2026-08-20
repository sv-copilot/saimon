"""CrewAI LLM builder for the crew service (saimon-side).

Builds a ``crewai.LLM`` bound to the routed DeepSeek model, reusing the #92
resolver. CrewAI is imported lazily here (and only here) so the other eight
saimon services never pull the dependency.

The service package is named ``saimon_mcp`` (not ``mcp``) deliberately:
crewai 1.14+ eagerly imports ``mcp.shared.message`` from the PyPI ``mcp``
distribution (via crewai.agent.core → crewai.mcp.tool_resolver →
crewai.mcp.transports.base), and a top-level ``mcp`` package would shadow it
with ``ModuleNotFoundError: mcp.shared`` (SAIMON-CREW-LLM-FIX-1, #190).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger("saimon.crew.llm")

NO_API_KEY_REASON = "no DEEPSEEK_API_KEY"


@dataclass(frozen=True)
class CrewLLMResolution:
    """Result of resolving the crew LLM.

    ``llm`` is None when the LLM is unavailable; ``reason`` names the true
    cause so callers surface it instead of a misleading blanket message.
    """

    llm: Any | None
    reason: str | None = None  # human-readable cause, set only when llm is None


def make_crew_llm(route: str) -> CrewLLMResolution:
    """Resolve a crewai.LLM for ``route``, fail-closed with an honest reason.

    Returns ``CrewLLMResolution(llm, None)`` on success, or
    ``CrewLLMResolution(None, reason)`` where ``reason`` names the true cause:
    missing key, crewai import/dependency failure, or undeclared route.
    ``route`` must be a declared ``saimon.*`` route (never a ``crew.*`` tool
    contract).
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        reason = NO_API_KEY_REASON
        _log.warning("crew LLM unavailable: %s", reason)
        return CrewLLMResolution(None, reason)

    try:
        from crewai import LLM
    except Exception as exc:  # noqa: BLE001 — fail-closed on any import/dep failure
        reason = f"crewai import failed: {type(exc).__name__}: {exc}"
        _log.exception("crew LLM unavailable: %s", reason)
        return CrewLLMResolution(None, reason)

    from research_shared import model_routing

    try:
        params = model_routing.route_params(route)
    except KeyError:
        reason = f"undeclared model route {route!r}"
        _log.warning("crew LLM unavailable: %s", reason)
        return CrewLLMResolution(None, reason)

    return CrewLLMResolution(
        LLM(
            model=params["model"],
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=api_key,
            temperature=params["temperature"],
            max_tokens=params["max_tokens"],
        )
    )
