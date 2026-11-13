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
        from saimon_mcp.crew.llm import make_crew_llm

        resolved = make_crew_llm("saimon.research")
        assert resolved.llm is None
        # Honest reason: the key is genuinely absent.
        assert resolved.reason == "no DEEPSEEK_API_KEY"

    def test_make_crew_llm_binds_routed_deepseek_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        class FakeLLM:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setitem(sys.modules, "crewai", SimpleNamespace(LLM=FakeLLM))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from saimon_mcp.crew.llm import make_crew_llm

        resolved = make_crew_llm("saimon.research")
        assert resolved.llm is not None
        assert resolved.reason is None
        assert captured["model"] == "deepseek-v4-pro"
        assert captured["api_key"] == "sk-test"
        assert captured["base_url"].startswith("https://api.deepseek.com")


class TestCrewLLMFailClosed:
    """#190 — honest fail-closed: surface the real cause, never a blanket message.

    P6 failed with `ModuleNotFoundError: mcp.shared` but the service reported
    "no DEEPSEEK_API_KEY" (the key WAS set). Each failure mode must now produce
    a reason that names the true cause.
    """

    def test_surfaces_crewai_import_error_when_key_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate the P6 failure: crewai 1.14+ eagerly imports mcp.shared and
        the local package shadowing raises ModuleNotFoundError('mcp.shared')."""
        import importlib.abc

        class _RaisingFinder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "crewai" or fullname.startswith("crewai."):
                    raise ModuleNotFoundError("No module named 'mcp.shared'")
                return None

        monkeypatch.setattr(sys, "meta_path", [_RaisingFinder()] + list(sys.meta_path))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from saimon_mcp.crew.llm import make_crew_llm

        resolved = make_crew_llm("saimon.research")
        assert resolved.llm is None
        assert resolved.reason is not None
        assert "crewai import failed" in resolved.reason
        assert "mcp.shared" in resolved.reason
        # Never blame the key when it is present.
        assert "no DEEPSEEK_API_KEY" not in resolved.reason

    def test_surfaces_undeclared_route(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """crew.* tool contracts must map to declared saimon.* routes; an
        undeclared route is surfaced as such."""
        monkeypatch.setitem(sys.modules, "crewai", SimpleNamespace(LLM=object))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from saimon_mcp.crew.llm import make_crew_llm

        resolved = make_crew_llm("crew.research")  # undeclared
        assert resolved.llm is None
        assert resolved.reason is not None
        assert "undeclared" in resolved.reason
        assert "crew.research" in resolved.reason


class TestCrewPin:
    def test_crewai_version_within_1_0_to_2_0(self) -> None:
        # crewai moved to its own file: 1.x requires Python <3.14, and the core
        # services and test suite must install on any supported Python.
        req = (REPO_ROOT / "requirements-crew.txt").read_text(encoding="utf-8")
        assert "crewai>=1.0.0,<2.0.0" in req

    def test_mcp_pinned_to_crewai_compatible_range(self) -> None:
        """#190 — crewai 1.14.1 declares `mcp~=1.26.0` (verified from PyPI
        metadata); requirements must pin mcp to that 1.x range. `mcp.shared`
        exists in mcp 1.x, so a `mcp<1.0` pin would be wrong."""
        req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "mcp>=1.26.0,<2.0.0" in req


class TestNoShadowing:
    """#190 — the saimon service package must not shadow the PyPI `mcp` dist.

    crewai 1.14+ eagerly imports `mcp.shared.message` (via crewai.agent.core →
    crewai.mcp.tool_resolver → crewai.mcp.transports.base). A top-level `mcp`
    package in the repo shadows the PyPI distribution and breaks `import crewai`
    with `ModuleNotFoundError: mcp.shared` — the P6 bug.
    """

    def test_no_top_level_mcp_package_shadows_pypi(self) -> None:
        assert (REPO_ROOT / "saimon_mcp").is_dir()
        assert not (REPO_ROOT / "mcp" / "__init__.py").exists()

    def test_pypi_mcp_importable_when_installed(self) -> None:
        mcp = pytest.importorskip("mcp")
        from mcp.shared.message import SessionMessage  # noqa: F401

        # The imported `mcp` must be the PyPI distribution, not a local package
        # that shadows it (which would break `import crewai`).
        #
        # Checking "not under the repo root" is wrong: a virtualenv created inside
        # the project — the most common layout — puts site-packages under the repo
        # root, and the test then fails for a perfectly good install. Check that
        # the module resolves from site-packages instead.
        module_path = str(mcp.__file__)
        in_site_packages = "site-packages" in module_path or "dist-packages" in module_path
        assert in_site_packages, f"mcp resolved outside site-packages: {module_path}"


class TestCrewIsolation:
    def test_no_sibling_service_imports_crewai(self) -> None:
        mcp_root = REPO_ROOT / "saimon_mcp"
        offenders = []
        for server in mcp_root.glob("*/server.py"):
            if server.parent.name == "crew":
                continue
            text = server.read_text(encoding="utf-8")
            if "import crewai" in text or "from crewai" in text:
                offenders.append(str(server))
        assert offenders == []
