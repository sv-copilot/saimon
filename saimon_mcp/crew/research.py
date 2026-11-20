"""crew.research@v1 — grounded research, with the search step done explicitly.

The previous version built a CrewAI agent and told it to use its tools. No tools
were ever attached, so the agent had nothing to call; and the deployed image does
not carry the optional crewai dependency, so the tool returned "crew LLM
unavailable — crewai import failed" while the service reported healthy.

Retrieval is not something a prompt can ask for. This module searches the
knowledge graph, hands the passages to the model, and refuses to produce a
"confirmed" list when retrieval returned nothing — the three-part answer
describes what the corpus supports, not what the model remembers.
"""

from __future__ import annotations

import json as _json
import logging as _logging
import os
from typing import Any

_log = _logging.getLogger("saimon.crew.research")

_PROMPT = """Answer the topic using ONLY the numbered passages below.

Return a JSON object with exactly three arrays:
- "confirmed": facts stated in the passages, each as a sentence
- "inferred": conclusions that follow from confirmed facts but are not stated
- "unavailable": aspects of the topic the passages do not address

Quote names, numbers and identifiers exactly as the passage writes them. Do not
use knowledge from outside the passages.

Passages:
{context}

TOPIC: {topic}
"""


def _search_url() -> str:
    return os.getenv("SEARCH_MCP_URL", "http://search-mcp:8001").rstrip("/")


def _api_key() -> str:
    return (os.getenv("SAIMON_API_KEY") or "").split(",")[0].strip()


def search_passages(topic: str, limit: int = 8) -> list[dict[str, Any]]:
    """Retrieve passages from the knowledge graph. Empty list on any failure.

    A retrieval failure reads as no evidence rather than an exception: the tool
    contract has a channel for "unavailable", and a raised error would turn a
    quiet corpus into a 500.
    """
    import urllib.error
    import urllib.request
    import uuid

    key = _api_key()
    if not key:
        return []
    body = _json.dumps({
        "trace_id": str(uuid.uuid4()),
        "content_type": "crew_research",
        "parameters": {"query": topic, "limit": limit},
    }).encode()
    request = urllib.request.Request(
        _search_url() + "/tools/search_knowledge_graph",
        data=body,
        headers={"Content-Type": "application/json", "X-Saimon-API-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = _json.loads(response.read()) or {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        _log.warning("crew research retrieval failed: %s", exc)
        return []
    results = (payload.get("data") or {}).get("results") or []
    return [row for row in results if row.get("body")]


def format_context(passages: list[dict[str, Any]]) -> str:
    lines = []
    for index, row in enumerate(passages, 1):
        title = row.get("title") or "untitled"
        body = (row.get("body") or "").strip()
        lines.append(f"[{index}] {title}: {body}")
    return "\n\n".join(lines)


def parse_answer(raw: str) -> dict[str, Any] | None:
    """Pull the JSON object out of a model reply, tolerating prose around it."""
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = _json.loads(text[start : end + 1])
    except _json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    def _as_list(value: Any) -> list[str]:
        return [str(item) for item in value] if isinstance(value, list) else []

    return {
        "confirmed": _as_list(parsed.get("confirmed")),
        "inferred": _as_list(parsed.get("inferred")),
        "unavailable": _as_list(parsed.get("unavailable")),
    }


async def run_research(topic: str, max_messages: int = 10) -> dict[str, Any]:
    """Retrieve, answer from the passages, and say what the corpus does not cover."""
    del max_messages  # the direct path sends what it retrieved; there is no history
    passages = search_passages(topic)
    if not passages:
        return {
            "confirmed": [],
            "inferred": [],
            "unavailable": [
                (
                    "no passages retrieved — the corpus has nothing on this "
                    "topic, or retrieval is unreachable"
                )
            ],
        }

    from research_shared.llm import LLMClient, LLMConfig

    config = LLMConfig.from_env()
    if not config.api_key:
        return {
            "confirmed": [],
            "inferred": [],
            "unavailable": ["crew LLM unavailable — DEEPSEEK_API_KEY is not set"],
        }

    prompt = _PROMPT.format(context=format_context(passages), topic=topic)
    try:
        raw = await LLMClient(config).generate(prompt)
    except Exception as exc:  # noqa: BLE001 — the contract reports, it does not raise
        _log.warning("crew research generation failed: %s", exc)
        return {
            "confirmed": [],
            "inferred": [],
            "unavailable": [f"crew LLM call failed — {type(exc).__name__}"],
        }

    parsed = parse_answer(raw)
    if parsed is None:
        return {
            "confirmed": [],
            "inferred": [],
            "unavailable": ["could not parse crew output"],
        }
    parsed["citations"] = [
        {"title": row.get("title"), "id": row.get("id")} for row in passages
    ]
    return parsed
