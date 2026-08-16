"""Tests for mcp.evaluate.writing_style — style/voice consistency (slice #77).

The primitive scores a scene against per-character/POV voice profiles and
returns drift findings that cite the offending line and the expected profile.
Tests use fixture voice profiles; no live MCP servers or LLM are required.
"""

from __future__ import annotations

import sys

from mcp.evaluate.writing_style import evaluate_voice

PROFILES = [
    {
        "name": "Mara Voss",
        "markers": ["quiet", "measured"],
        "avoid": ["shouted", "brisk"],
    }
]


class TestEvaluateVoice:
    def test_matching_scene_scores_high(self):
        result = evaluate_voice("She spoke in a quiet, measured tone.", PROFILES)
        assert result["score"] >= 70

    def test_mismatched_scene_scores_low(self):
        result = evaluate_voice("She shouted briskly across the room.", PROFILES)
        assert result["score"] < 50

    def test_drift_findings_cite_line_and_profile(self):
        result = evaluate_voice("She shouted across the room.", PROFILES)
        assert result["findings"]
        finding = result["findings"][0]
        assert finding["finding"] == "voice_drift"
        assert finding["profile"] == "Mara Voss"
        assert "shouted" in finding["line"].lower()

    def test_score_is_bounded(self):
        samples = [
            "She spoke in a quiet, measured tone.",
            "She shouted briskly across the room.",
            "",
            "neutral text with no markers or avoid words",
        ]
        for text in samples:
            assert 0 <= evaluate_voice(text, PROFILES)["score"] <= 100

    def test_empty_profiles_yield_no_findings(self):
        result = evaluate_voice("anything at all", [])
        assert result["findings"] == []

    def test_empty_scene_scores_zero(self):
        result = evaluate_voice("", PROFILES)
        assert result["score"] == 0

    def test_profile_scores_reported(self):
        result = evaluate_voice("She spoke quietly.", PROFILES)
        assert result["profiles"]
        assert result["profiles"][0]["name"] == "Mara Voss"


class TestEvaluateVoiceRoute:
    def test_exposed_as_evaluate_mcp_tool(self, monkeypatch):
        monkeypatch.setenv("SAIMON_API_KEY", "sk-test-evaluate-key")
        sys.modules.pop("mcp.evaluate.server", None)
        from fastapi.testclient import TestClient

        from mcp.evaluate.server import app

        client = TestClient(app)
        response = client.post(
            "/tools/evaluate_voice",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000077",
                "content_type": "evaluate",
                "parameters": {
                    "scene_text": "She spoke in a quiet, measured tone.",
                    "voice_profiles": PROFILES,
                },
            },
            headers={"X-Saimon-API-Key": "sk-test-evaluate-key"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert "score" in body["data"]
        assert body["data"]["score"] >= 70

    def test_requires_scene_text(self, monkeypatch):
        monkeypatch.setenv("SAIMON_API_KEY", "sk-test-evaluate-key")
        sys.modules.pop("mcp.evaluate.server", None)
        from fastapi.testclient import TestClient

        from mcp.evaluate.server import app

        client = TestClient(app)
        response = client.post(
            "/tools/evaluate_voice",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000077",
                "content_type": "evaluate",
                "parameters": {"voice_profiles": PROFILES},
            },
            headers={"X-Saimon-API-Key": "sk-test-evaluate-key"},
        )
        body = response.json()
        assert body["status"] == "error"
        assert any("scene_text" in e for e in (body.get("errors") or []))
