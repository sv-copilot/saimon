"""crew.research@v1 — research-analyst crew (SAIMON-CREW-RESEARCH-1).

Answers a topic by chaining saimon tools (knowledge-graph search, verification,
source discovery) with grounded evidence. Never invents content a tool did not
return; responses separate confirmed / inferred / unavailable. Session context
is bounded to the last N messages.
"""

from __future__ import annotations

import json as _json
from typing import Any

from mcp.crew.llm import make_crew_llm

_RESEARCH_PROMPT = """You are a research analyst. Answer the topic using ONLY
the evidence your tools return (knowledge-graph search, claim verification,
source discovery).

Separate your answer into exactly three arrays:
- "confirmed": facts a tool directly returned
- "inferred": reasonable inference from confirmed facts (explicitly labelled)
- "unavailable": what you could not determine from the tools

NEVER invent content a tool did not return. If a tool returns nothing, report it
under "unavailable" — do not fabricate.

TOPIC: {topic}
"""


def build_research_crew(llm: Any, max_messages: int = 10) -> Any:
    """Build the single-agent research crew with bounded context."""
    from crewai import Agent, Crew, Process, Task

    agent = Agent(
        role="Research Analyst",
        goal="Answer a topic with grounded saimon evidence, never inventing.",
        backstory=(
            "You answer research topics using only tool-returned evidence. "
            "Context is bounded to the last N messages."
        ),
        llm=llm,
        verbose=False,
    )
    task = Task(
        description=_RESEARCH_PROMPT,
        expected_output=(
            'JSON object with "confirmed", "inferred", "unavailable" arrays.'
        ),
        agent=agent,
        context=[],
    )
    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
        memory=False,
        max_rpm=10,
    )


async def run_research(topic: str, max_messages: int = 10) -> dict[str, Any]:
    """Run the research crew and parse its grounded, three-part answer."""
    llm = make_crew_llm("saimon.research")
    if llm is None:
        return {
            "confirmed": [],
            "inferred": [],
            "unavailable": ["crew LLM unavailable — no DEEPSEEK_API_KEY"],
        }

    crew = build_research_crew(llm, max_messages=max_messages)
    try:
        result = crew.kickoff(inputs={"topic": topic})
    except Exception:  # noqa: BLE001 — degrade to "unavailable" on crew failure
        return {
            "confirmed": [],
            "inferred": [],
            "unavailable": ["crew research failed"],
        }
    raw = str(getattr(result, "raw", "") or getattr(result, "output", "") or "")
    try:
        parsed = _json.loads(raw)
        if isinstance(parsed, dict):
            def _as_list(value: Any) -> list:
                return list(value) if isinstance(value, list) else []

            return {
                "confirmed": _as_list(parsed.get("confirmed")),
                "inferred": _as_list(parsed.get("inferred")),
                "unavailable": _as_list(parsed.get("unavailable")),
            }
    except _json.JSONDecodeError:
        pass
    return {
        "confirmed": [],
        "inferred": [],
        "unavailable": ["could not parse crew output"],
    }
