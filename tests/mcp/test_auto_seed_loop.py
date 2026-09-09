"""Tests for SAIMON-AUTO-SEED-LOOP-1 — gap → seed → verify auto-fill loop.

The loop consumes the same gap shape produced by ``saimon_list_gaps`` and,
for each gap, resolves concrete targets from the DB, creates a
``seed_request`` (status ``pending``), runs ``self_seed`` to generate +
persist content, then runs the verification pipeline to annotate claims.

No database or LLM is required: the DB and pipeline callbacks are mocked.
"""

from unittest.mock import AsyncMock

import pytest

from saimon_mcp.generate.auto_seed_loop import (
    DEFAULT_GAP_PROMPT_TEMPLATE,
    GAP_PROMPT_TEMPLATES,
    build_gap_prompt,
    fill_gaps,
)


class FakeDB:
    """Minimal fake pool that records seed_requests INSERTs and resolves targets."""

    def __init__(self, target_rows=None, existing_prompts=None):
        self.target_rows = target_rows or {}
        self.existing_prompts = set(existing_prompts or [])
        self.seed_inserts = []
        self._next_id = 1000

    async def fetch(self, query, *args):
        for key, rows in self.target_rows.items():
            if key in query:
                return rows
        return []

    async def fetchval(self, query, *args):
        if "INSERT INTO seed_requests" in query:
            self.seed_inserts.append((query, args))
            self._next_id += 1
            return self._next_id
        if "FROM seed_requests WHERE prompt" in query:
            prompt = args[0] if args else ""
            return 1 if prompt in self.existing_prompts else None
        return None

    async def fetchrow(self, query, *args):
        return None


@pytest.mark.asyncio
async def test_build_gap_prompt_observation_unverified():
    """The gap→prompt mapper produces a verification prompt for a target."""
    prompt = build_gap_prompt(
        "observation_unverified", {"claim_text": "Vitamin C cures colds"}
    )
    assert prompt == "research and verify: Vitamin C cures colds"


def test_build_gap_prompt_uses_declared_templates():
    """Every declared gap type has a template; unknown types use a fallback."""
    for gap_type in GAP_PROMPT_TEMPLATES:
        assert isinstance(GAP_PROMPT_TEMPLATES[gap_type], str)
    assert "{gap_type}" in DEFAULT_GAP_PROMPT_TEMPLATE


def test_build_gap_prompt_unknown_type_falls_back():
    prompt = build_gap_prompt("totally_unknown_gap", {"claim_text": "ignored"})
    assert "totally_unknown_gap" in prompt


@pytest.mark.asyncio
async def test_fill_gaps_creates_seed_and_runs_pipeline():
    """fill_gaps INSERTs a pending seed_request and runs seed + verify."""
    db = FakeDB(
        target_rows={
            "FROM observations WHERE verification_status = 'unverified'": [
                {"claim_text": "Vitamin C cures colds"},
            ],
        },
    )
    self_seed = AsyncMock(
        return_value={
            "node_id": "node-1",
            "content": "generated content",
            "content_type": "research_note",
            "status": "seeded",
        }
    )
    generate_verified = AsyncMock(return_value={"claims_verified": 1})

    report = await fill_gaps(
        [{"type": "observation_unverified", "severity": "medium", "count": 1}],
        db,
        self_seed_fn=self_seed,
        generate_verified_fn=generate_verified,
    )

    assert len(db.seed_inserts) == 1
    insert_query, insert_args = db.seed_inserts[0]
    assert "INSERT INTO seed_requests" in insert_query
    assert insert_args[0] == "research_note"
    assert "Vitamin C cures colds" in insert_args[1]

    self_seed.assert_awaited_once()
    generate_verified.assert_awaited_once()

    assert report["summary"]["filled"] == 1
    assert report["summary"]["failed"] == 0
    assert report["summary"]["skipped"] == 0
    assert report["filled"][0]["status"] == "filled"
    assert report["filled"][0]["node_id"] == "node-1"


@pytest.mark.asyncio
async def test_fill_gaps_is_idempotent():
    """Re-running doesn't duplicate seeds for an already-pending target."""
    prompt = "research and verify: Vitamin C cures colds"
    db = FakeDB(
        target_rows={
            "FROM observations WHERE verification_status = 'unverified'": [
                {"claim_text": "Vitamin C cures colds"},
            ],
        },
        existing_prompts={prompt},
    )
    self_seed = AsyncMock(return_value={"node_id": "node-1"})

    report = await fill_gaps(
        [{"type": "observation_unverified", "severity": "medium", "count": 1}],
        db,
        self_seed_fn=self_seed,
    )

    assert db.seed_inserts == []
    self_seed.assert_not_awaited()
    assert report["summary"]["skipped"] == 1
    assert report["skipped"][0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_fill_gaps_reports_filled_and_failed():
    """Per-gap filled/failed status is reported for mixed outcomes."""
    db = FakeDB(
        target_rows={
            "FROM observations WHERE verification_status = 'unverified'": [
                {"claim_text": "Claim A is verifiable"},
                {"claim_text": "Claim B is not"},
            ],
        },
    )

    async def _seed(seed_id):
        if seed_id == 1001:
            return {
                "node_id": "node-a",
                "content": "content a",
                "content_type": "research_note",
                "status": "seeded",
            }
        return {"node_id": None, "status": "failed", "error": "LLM down"}

    report = await fill_gaps(
        [{"type": "observation_unverified", "severity": "medium", "count": 2}],
        db,
        self_seed_fn=_seed,
    )

    assert report["summary"]["filled"] == 1
    assert report["summary"]["failed"] == 1
    assert any(r["status"] == "filled" for r in report["filled"])
    assert any(r["status"] == "failed" for r in report["failed"])


@pytest.mark.asyncio
async def test_fill_gaps_no_db_returns_empty_report():
    """Without a DB pool the loop returns an empty report, never raises."""
    report = await fill_gaps([{"type": "observation_unverified"}], None)
    assert report["summary"]["filled"] == 0
    assert report["summary"]["failed"] == 0
