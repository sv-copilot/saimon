"""Tests for mcp.verify.writing_continuity — continuity verification.

The primitive compares a scene against a universe knowledge graph and flags
continuity breaks (e.g. a character acting after death).  Tests inject a
fixture ``kg`` lookup so no live database is required.
"""

from __future__ import annotations

from typing import Any

from mcp.verify.writing_continuity import extract_entities, verify_against_kg

# Fixture universe: Mara Voss is deceased, Jonas Reed is alive.
FIXTURE_UNIVERSE: dict[str, dict[str, Any]] = {
    "Mara Voss": {
        "title": "Mara Voss",
        "content_type": "character",
        "life_status": "deceased",
    },
    "Jonas Reed": {
        "title": "Jonas Reed",
        "content_type": "character",
        "life_status": "alive",
    },
}


def make_kg(universe: dict[str, dict[str, Any]] | None = None):
    """Build a fake async KG lookup over a fixture universe."""
    universe = universe or FIXTURE_UNIVERSE

    async def kg(names: list[str]) -> list[dict[str, Any]]:
        return [universe[n] for n in names if n in universe]

    return kg


class TestExtractEntities:
    def test_extracts_names(self):
        names = extract_entities("Mara Voss and Jonas Reed walked in.")
        assert "Mara Voss" in names
        assert "Jonas Reed" in names

    def test_deduplicates(self):
        names = extract_entities("Mara Voss said hi. Mara Voss left.")
        assert names.count("Mara Voss") == 1

    def test_empty_scene(self):
        assert extract_entities("") == []


class TestVerifyAgainstKg:
    async def test_consistent_scene_zero_flags(self):
        """An alive character acting is not a continuity break."""
        findings = await verify_against_kg(
            "Jonas Reed walked into the room and said hello.",
            "universe-1",
            kg=make_kg(),
        )
        assert findings == []

    async def test_deceased_character_active_flags(self):
        """A deceased character acting flags a continuity break."""
        findings = await verify_against_kg(
            "Mara Voss walked into the room and spoke quietly.",
            "universe-1",
            kg=make_kg(),
        )
        assert len(findings) == 1
        assert findings[0]["flag"] == "continuity_break"
        assert findings[0]["severity"] == "high"
        assert "Mara Voss" in findings[0]["reason"]

    async def test_memory_mention_not_flagged(self):
        """A deceased character mentioned in memory is not flagged."""
        findings = await verify_against_kg(
            "Jonas remembered Mara Voss walking into the room.",
            "universe-1",
            kg=make_kg(),
        )
        assert findings == []

    async def test_no_names_zero_flags(self):
        findings = await verify_against_kg(
            "the rain fell and the wind howled.",
            "universe-1",
            kg=make_kg(),
        )
        assert findings == []

    async def test_no_kg_degrades_to_empty(self):
        """Without a KG lookup the primitive degrades gracefully."""
        findings = await verify_against_kg(
            "Mara Voss walked in.", "universe-1", kg=None
        )
        assert findings == []

    async def test_finding_shape(self):
        findings = await verify_against_kg(
            "Mara Voss opened the door.", "universe-1", kg=make_kg()
        )
        assert findings
        for finding in findings:
            assert set(finding) == {"flag", "severity", "reason"}
