"""CrewAI LLM builder for the crew service (saimon-side).

Builds a ``crewai.LLM`` bound to the routed DeepSeek model, reusing the #92
resolver. CrewAI is imported lazily here (and only here) so the other eight
saimon services never pull the dependency.
"""

from __future__ import annotations

import os
from typing import Any


def make_crew_llm(route: str) -> Any | None:
    """Build a crewai.LLM for ``route``, fail-closed on missing key/package.

    Returns None when ``DEEPSEEK_API_KEY`` is missing or crewai is not
    installed. Model/temperature/max_tokens resolve from the canonical model
    routing config (env-overridable via SAIMON_*).
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    try:
        from crewai import LLM
    except ImportError:
        return None

    from research_shared import model_routing

    try:
        params = model_routing.route_params(route)
    except KeyError:
        return None
    return LLM(
        model=params["model"],
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
        temperature=params["temperature"],
        max_tokens=params["max_tokens"],
    )
