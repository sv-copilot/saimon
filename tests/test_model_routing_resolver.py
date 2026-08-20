"""Tests for saimon-side config-driven model routing (SAIMON-MODEL-ROUTING-1).

Covers: route→model resolution for the four saimon routes, SAIMON_* env
override precedence, the declared-models allowlist, and vendored-copy parity
with the canonical planning config. All network-free.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_shared import model_routing
from research_shared.llm import LLMConfig


@pytest.fixture
def _isolate_planning_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the resolver to use the vendored copy unless a test opts in.
    monkeypatch.delenv("PLANNING_CHECKOUT_PATH", raising=False)


@pytest.mark.usefixtures("_isolate_planning_checkout")
class TestRouteResolution:
    def test_saimon_generate_route_resolves_to_pro(self) -> None:
        assert model_routing.model_for_route("saimon.generate") == "deepseek-v4-pro"

    def test_saimon_verify_route_resolves_to_pro(self) -> None:
        assert model_routing.model_for_route("saimon.verify") == "deepseek-v4-pro"

    def test_saimon_evaluate_route_resolves_to_flash(self) -> None:
        assert model_routing.model_for_route("saimon.evaluate") == "deepseek-v4-flash"

    def test_saimon_extract_claims_route_resolves_to_flash(self) -> None:
        assert model_routing.model_for_route("saimon.extract_claims") == "deepseek-v4-flash"

    def test_unknown_route_raises(self) -> None:
        with pytest.raises(KeyError):
            model_routing.resolve_route("saimon.nonexistent")

    def test_route_params_include_model_temperature_max_tokens(self) -> None:
        params = model_routing.route_params("saimon.generate")
        assert params["model"] == "deepseek-v4-pro"
        assert "temperature" in params
        assert "max_tokens" in params


@pytest.mark.usefixtures("_isolate_planning_checkout")
class TestEnvOverridePrecedence:
    def test_from_env_defaults_to_pro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAIMON_LLM_MODEL", raising=False)
        config = LLMConfig.from_env()
        assert config.model == "deepseek-v4-pro"

    def test_saimon_llm_model_env_override_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAIMON_LLM_MODEL", "deepseek-v4-flash")
        config = LLMConfig.from_env(route="saimon.generate")
        assert config.model == "deepseek-v4-flash"

    def test_route_resolves_when_no_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAIMON_LLM_MODEL", raising=False)
        config = LLMConfig.from_env(route="saimon.extract_claims")
        assert config.model == "deepseek-v4-flash"


@pytest.mark.usefixtures("_isolate_planning_checkout")
class TestAllowlist:
    def test_allowlist_accepts_declared_models(self) -> None:
        assert model_routing.validate_allowlist(
            ["deepseek-v4-pro", "deepseek-v4-flash"]
        ) == []

    def test_allowlist_fails_on_undeclared_model(self) -> None:
        problems = model_routing.validate_allowlist(["gpt-4"])
        assert problems
        assert "gpt-4" in problems[0]

    def test_allowlist_never_declares_deepseek_chat(self) -> None:
        assert "deepseek-chat" not in model_routing.declared_models()


class TestVendoredParity:
    def test_vendored_copy_declares_saimon_routes(self) -> None:
        vendored = Path(model_routing.__file__).resolve().parent / "model_routing.json"
        cfg = json.loads(vendored.read_text(encoding="utf-8"))
        routes = cfg["routes"]
        for route, tier in {
            "saimon.generate": "reasoning",
            "saimon.verify": "reasoning",
            "saimon.evaluate": "classification",
            "saimon.extract_claims": "mechanical",
        }.items():
            assert routes[route] == tier

    def test_vendored_copy_matches_canonical_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canonical = model_routing.canonical_config_path()
        if canonical is None:
            pytest.skip("no canonical planning checkout available")
        vendored = Path(model_routing.__file__).resolve().parent / "model_routing.json"
        canonical_cfg = json.loads(canonical.read_text(encoding="utf-8"))
        vendored_cfg = json.loads(vendored.read_text(encoding="utf-8"))
        assert vendored_cfg["tiers"] == canonical_cfg["tiers"]
        assert set(vendored_cfg["routes"]) == set(canonical_cfg["routes"])
