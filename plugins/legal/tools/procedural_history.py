"""procedural_history.py — procedural timeline tool (legal tool 9/10, #75).

Composes search + generate: build a structured procedural timeline from
opinion, docket, and brief events.  Deterministic — no network I/O.
"""

from __future__ import annotations

from typing import Any, ClassVar

_STAGE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("certiorari", "certiorari"),
    ("cert.", "certiorari"),
    ("appeal", "appeal"),
    ("complaint", "filing"),
    ("filed", "filing"),
    ("removed", "filing"),
    ("brief", "briefing"),
    ("opinion", "decision"),
    ("decided", "decision"),
    ("decision", "decision"),
    ("judgment", "decision"),
    ("ruling", "decision"),
    ("order", "decision"),
)


def _stage_of(event: str) -> str:
    text = (event or "").lower()
    for keyword, stage in _STAGE_KEYWORDS:
        if keyword in text:
            return stage
    return "other"


def extract_procedural_history(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a structured timeline from procedural events.

    Events are sorted by date and each is tagged with an inferred stage
    (filing, briefing, appeal, certiorari, decision, or other).
    """
    cleaned: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        date = str(event.get("date", "")).strip()
        if not date:
            continue
        cleaned.append(
            {
                "date": date,
                "event": str(event.get("event", "")).strip() or "unnamed event",
                "court": str(event.get("court", "")).strip() or None,
                "source": str(event.get("source", "")).strip() or None,
            }
        )

    # Stable sort: date first, then original input order for equal dates.
    indexed = sorted(enumerate(cleaned), key=lambda pair: (pair[1]["date"], pair[0]))
    timeline = [{**event, "stage": _stage_of(event["event"])} for _, event in indexed]

    stages: list[str] = []
    seen_stages: set[str] = set()
    for entry in timeline:
        if entry["stage"] not in seen_stages:
            seen_stages.add(entry["stage"])
            stages.append(entry["stage"])

    event_count = len(timeline)
    if timeline:
        summary = (
            f"{event_count} procedural events from {timeline[0]['date']} to "
            f"{timeline[-1]['date']}."
        )
    else:
        summary = "No procedural events."

    return {
        "timeline": timeline,
        "stages": stages,
        "event_count": event_count,
        "summary": summary,
    }


class ExtractProceduralHistoryTool:
    """DomainTool wrapper for :func:`extract_procedural_history`."""

    name = "legal.extract_procedural_history"
    description = (
        "Build a structured procedural timeline from opinion, docket, and "
        "brief events, each tagged with an inferred stage."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "events": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["events"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        events = arguments.get("events")
        if not isinstance(events, list):
            raise TypeError("Parameter 'events' must be a list.")
        return extract_procedural_history(events)
