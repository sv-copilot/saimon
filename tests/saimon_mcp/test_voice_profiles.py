"""Tests for SAIMON-VOICE-PROFILE-AUDIT-1 — confirm + wire ``spencer-*`` voices.

Covers the slice's TDD contract:

- every handoff §5 content type resolves a declared ``spencer-*`` voice profile
  (asserted against ``list_content_types`` output, not just seed data),
- the five ``spencer-*`` voice profiles are declared as canonical profiles,
- the universe/storage-only types that are *intentionally* unbound are pinned to
  ``voice_profile=None`` so the operator flag can't silently drift.

The handoff §5 map (``.docs/content_ops_saimon.md``) lists the content-ops types
and their voice profile bindings; the mapping below is the executable mirror of
``docs/voice-profile-mapping.md``.
"""

from __future__ import annotations

import sys
import uuid

import pytest
from fastapi.testclient import TestClient

from research_shared import seed_data

# ---------------------------------------------------------------------------
# Canonical mappings (mirror of docs/voice-profile-mapping.md)
# ---------------------------------------------------------------------------

# Handoff §5 "Content type -> voice profile -> site section" map.  Includes the
# seven explicitly-listed types plus ``white_paper`` and the "remainder" content
# types that §5 asks us to confirm via ``list_content_types``.
CONTENT_TYPE_VOICE_MAP: dict[str, str] = {
    "blog_post": "spencer-default",
    "summary": "spencer-default",
    "research_note": "spencer-technical",
    "social_post": "spencer-casual",
    "email_draft": "spencer-default",
    "press_release": "spencer-formal",
    "case_study": "spencer-marketing",
    "white_paper": "spencer-technical",
    "job_posting": "spencer-formal",
    "meeting_notes": "spencer-default",
    "proposal": "spencer-formal",
    "tutorial": "spencer-technical",
    "product_review": "spencer-technical",
    "bibliography": "spencer-technical",
}

# The five canonical spencer-* voice profiles declared in seed_data.
DECLARED_SPENCER_PROFILES: set[str] = {
    "spencer-default",
    "spencer-technical",
    "spencer-casual",
    "spencer-formal",
    "spencer-marketing",
}

# Universe content types are storage-only (world-building), not generation
# oriented; per SAIMON-UNIVERSE-TYPES they are deliberately left unbound.
# This set pins that decision so it is flagged rather than silently regressed.
UNBOUND_STORAGE_TYPES: set[str] = {
    "character",
    "location",
    "faction",
    "timeline_event",
    "lore_rule",
}


# ---------------------------------------------------------------------------
# Fixtures (self-contained; no conftest at tests/saimon_mcp/)
# ---------------------------------------------------------------------------


@pytest.fixture
def api_key() -> str:
    return "sk-test-voice-profile-key"


@pytest.fixture
def client(api_key, monkeypatch):
    """Return a TestClient for the generate-mcp FastAPI app."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    sys.modules.pop("saimon_mcp.generate.server", None)
    from saimon_mcp.generate.server import app

    return TestClient(app)


@pytest.fixture
def auth_headers(api_key):
    return {"X-Saimon-API-Key": api_key}


@pytest.fixture
def listed_types(client, auth_headers):
    """Return the ``list_content_types`` output keyed by name."""

    response = client.post(
        "/tools/list_content_types",
        json={"trace_id": str(uuid.uuid4()), "content_type": "generate"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("success", "degraded")
    return {ct["name"]: ct for ct in data["data"]["types"]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVoiceProfileBindings:
    """Every handoff §5 content type resolves a declared spencer-* profile."""

    def test_all_section5_types_listed(self, listed_types):
        for content_type in CONTENT_TYPE_VOICE_MAP:
            assert content_type in listed_types, (
                f"§5 content type {content_type!r} missing from "
                "list_content_types output"
            )

    def test_every_section5_type_bound_to_spencer_profile(self, listed_types):
        for content_type, expected_profile in CONTENT_TYPE_VOICE_MAP.items():
            voice_profile = listed_types[content_type].get("voice_profile")
            assert voice_profile == expected_profile, (
                f"{content_type!r} expected voice_profile "
                f"{expected_profile!r}, got {voice_profile!r}"
            )
            assert voice_profile in DECLARED_SPENCER_PROFILES

    def test_mapping_uses_only_declared_profiles(self):
        assert set(CONTENT_TYPE_VOICE_MAP.values()) <= DECLARED_SPENCER_PROFILES


class TestDeclaredVoiceProfiles:
    """The five spencer-* profiles exist as canonical voice profiles."""

    def test_seed_data_declares_all_spencer_profiles(self):
        declared = {vp["name"] for vp in seed_data.VOICE_PROFILES}
        assert DECLARED_SPENCER_PROFILES <= declared


class TestUniverseTypesFlaggedUnbound:
    """Universe/storage-only types stay unbound (flagged, not silently wired)."""

    def test_universe_types_listed(self, listed_types):
        for content_type in UNBOUND_STORAGE_TYPES:
            assert content_type in listed_types, (
                f"universe type {content_type!r} missing from "
                "list_content_types output"
            )

    def test_universe_types_remain_unbound(self, listed_types):
        for content_type in UNBOUND_STORAGE_TYPES:
            assert listed_types[content_type].get("voice_profile") is None, (
                f"universe type {content_type!r} is storage-only and must "
                "remain unbound (voice_profile=None)"
            )
