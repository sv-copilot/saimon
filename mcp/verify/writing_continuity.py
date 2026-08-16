"""writing_continuity.py — continuity & character-consistency verification.

Domain-agnostic primitive for the writing domain: compare a scene against the
universe knowledge graph and flag continuity breaks (e.g. a character acting
after death) and character inconsistencies.

The primitive is DB-optional: callers inject a ``kg`` lookup callable, or
rely on the module-level database pool (``set_db_pool``) which
``mcp.verify.server`` keeps in sync with the live knowledge graph.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

# A KG lookup: given entity names, return matching nodes asynchronously.
# Each node dict carries at least ``title``, ``content_type``, ``life_status``.
KGLookup = Callable[[list[str]], Awaitable[list[dict[str, Any]]]]

# Capitalized multi-word names (with optional surname prefixes/suffixes).
_NAME_PATTERN = re.compile(
    r"\b[A-Z][a-z]+ (?:van |de |von |del |Mc|Mac|O')?"
    r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?\b"
)

_DECEASED_STATUSES = {"dead", "deceased", "killed", "passed away"}

_ACTIVE_VERBS = {
    "said", "says", "asked", "asks", "replied", "replies", "answered",
    "answers", "walked", "walks", "entered", "enters", "left", "leaves",
    "stood", "stands", "sat", "sits", "spoke", "speaks", "laughed",
    "laughs", "smiled", "smiles", "nodded", "nods", "reached", "reaches",
    "opened", "opens", "shouted", "shouts", "called", "calls", "kissed",
    "kisses", "hugged", "hugs", "drank", "drinks", "ate", "eats",
    "ran", "runs", "wrote", "writes", "drove", "drives",
}

_FLASHBACK_MARKERS = {
    "memory", "memories", "remembered", "remembers", "remembering",
    "recalled", "recalls", "recalling", "ghost", "spirit", "grave",
    "memorial", "flashback", "dream", "dreamed", "dreamt", "portrait",
    "photograph", "photo", "letter", "diary", "journal", "funeral",
    "eulogy", "vision", "hallucination", "imagined", "imagines",
}

# ---------------------------------------------------------------------------
# database pool (optional — set by mcp.verify.server)
# ---------------------------------------------------------------------------

_db_pool: Any = None


def set_db_pool(pool: Any | None) -> None:
    """Inject a DatabasePool for live knowledge-graph lookups."""
    global _db_pool
    _db_pool = pool


# ---------------------------------------------------------------------------
# entity extraction
# ---------------------------------------------------------------------------

def extract_entities(scene_text: str) -> list[str]:
    """Extract capitalized multi-word entity names from scene text."""
    if not scene_text:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for match in _NAME_PATTERN.findall(scene_text):
        name = match.strip()
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# continuity checks
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _active_mention(scene_text: str, name: str) -> bool:
    """Return True if ``name`` appears in an active (non-memory) sentence."""
    lowered_name = name.lower()
    for sentence in _split_sentences(scene_text):
        if lowered_name not in sentence.lower():
            continue
        words = {w.strip(".,!?;:\"'()") for w in sentence.lower().split()}
        if words & _FLASHBACK_MARKERS:
            continue  # memory/flashback mention — not a continuity break
        if words & _ACTIVE_VERBS:
            return True
    return False


def _check_character(
    scene_text: str, node: dict[str, Any]
) -> dict[str, Any] | None:
    """Flag a character node if it is deceased but acts in the scene."""
    life_status = (node.get("life_status") or "").strip().lower()
    if life_status not in _DECEASED_STATUSES:
        return None
    title = (node.get("title") or "").strip()
    if not title or not _active_mention(scene_text, title):
        return None
    return {
        "flag": "continuity_break",
        "severity": "high",
        "reason": (
            f"'{title}' is marked {life_status} in the universe but appears "
            "to act in the scene."
        ),
    }


# ---------------------------------------------------------------------------
# KG lookup
# ---------------------------------------------------------------------------

def _make_kg_lookup(universe_id: str) -> KGLookup:
    """Build a DB-backed KG lookup scoped to ``universe_id``."""

    async def lookup(names: list[str]) -> list[dict[str, Any]]:
        if _db_pool is None or not names:
            return []
        conditions: list[str] = []
        params: list[Any] = []
        for n in names:
            params.append(f"%{n}%")
            conditions.append(
                f"(title ILIKE ${len(params)} OR body ILIKE ${len(params)})"
            )
        params.append(str(universe_id))
        sql = (
            "SELECT title, content_type, "
            "COALESCE(metadata->>'status', metadata->>'life_status') "
            "AS life_status "
            "FROM knowledge_graph_nodes "
            "WHERE (" + " OR ".join(conditions) + ") "
            "AND (metadata->>'universe_id' = $" + str(len(params))
            + " OR user_id::text = $" + str(len(params)) + ")"
        )
        try:
            rows = await _db_pool.fetch(sql, *params)
            return [dict(r) for r in rows]
        except Exception:  # noqa: BLE001 — degrade to no findings
            return []

    return lookup


# ---------------------------------------------------------------------------
# public primitive
# ---------------------------------------------------------------------------

async def verify_against_kg(
    scene_text: str,
    universe_id: str,
    kg: KGLookup | None = None,
) -> list[dict[str, Any]]:
    """Flag continuity breaks by comparing a scene against the universe KG.

    Args:
        scene_text: The scene prose to verify.
        universe_id: Scope identifier for the universe knowledge graph.
        kg: Optional async lookup ``(names: list[str]) -> list[dict]``.
            When omitted, the module-level DB pool (if set) is used.

    Returns:
        A list of findings, each ``{"flag", "severity", "reason"}``.
    """
    names = extract_entities(scene_text)
    if not names:
        return []

    lookup = kg if kg is not None else _make_kg_lookup(universe_id)
    nodes = await lookup(names)

    findings: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("content_type") != "character":
            continue
        finding = _check_character(scene_text, node)
        if finding is not None:
            findings.append(finding)
    return findings
