"""Tests for the crew-mcp service scaffold (SAIMON-CREW-SERVICE-1)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestCrewService:
    def test_app_builds_and_health_ok(self, client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "crew-mcp"

    def test_tools_registered_research_and_extract_claims(
        self, client, auth_headers
    ) -> None:
        resp = client.get("/tools", headers=auth_headers)
        assert resp.status_code == 200
        names = [tool["name"] for tool in resp.json()["tools"]]
        assert "crew.research@v1" in names
        assert "crew.extract_claims@v1" in names


class TestCrewWiring:
    def test_make_crew_llm_fails_closed_without_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        from mcp.crew.llm import make_crew_llm

        assert make_crew_llm("saimon.research") is None

    def test_make_crew_llm_binds_routed_deepseek_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        class FakeLLM:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setitem(sys.modules, "crewai", SimpleNamespace(LLM=FakeLLM))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from mcp.crew.llm import make_crew_llm

        llm = make_crew_llm("saimon.research")
        assert llm is not None
        assert captured["model"] == "deepseek-v4-pro"
        assert captured["api_key"] == "sk-test"
        assert captured["base_url"].startswith("https://api.deepseek.com")


class TestCrewPin:
    def test_crewai_version_within_1_0_to_2_0(self) -> None:
        req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "crewai>=1.0.0,<2.0.0" in req


class TestCrewIsolation:
    def test_no_sibling_service_imports_crewai(self) -> None:
        mcp_root = REPO_ROOT / "mcp"
        offenders = []
        for server in mcp_root.glob("*/server.py"):
            if server.parent.name == "crew":
                continue
            text = server.read_text(encoding="utf-8")
            if "import crewai" in text or "from crewai" in text:
                offenders.append(str(server))
        assert offenders == []
