"""Tests for the model-routing A/B gate (SAIMON-MODEL-AB-TEST-1).

The gate is a pure function: recorded verdicts in -> allow/deny out. A saimon
route may only flip to a cheaper/free model after a green offline
``eval.py compare`` for the affected tier is recorded in
``model_ab_verdict.json``.
"""

from __future__ import annotations

from eval_harness import fixtures as fixtures_mod
from research_shared import model_routing
from research_shared.model_ab_gate import (
    check_model_swap,
    gate_routes,
    load_verdict_doc,
)

SAIMON_ROUTES = (
    "saimon.generate",
    "saimon.verify",
    "saimon.evaluate",
    "saimon.extract_claims",
)
MODEL_ROUTING_TIERS = ("generate", "verify", "evaluate", "extract_claims")


def _verdict(**overrides) -> dict:
    entry = {
        "route": "saimon.generate",
        "tier": "generate",
        "incumbent": "deepseek-v4-pro",
        "candidate": "deepseek-v4-flash",
        "verdict": "OK",
    }
    entry.update(overrides)
    return entry


class TestModelSwapGate:
    def test_no_change_is_allowed(self) -> None:
        decision = check_model_swap("deepseek-v4-pro", "deepseek-v4-pro", [])
        assert decision.allowed is True
        assert decision.reasons == []

    def test_swap_without_verdict_is_blocked(self) -> None:
        decision = check_model_swap("deepseek-v4-pro", "deepseek-v4-flash", [])
        assert decision.allowed is False
        assert decision.reasons

    def test_swap_with_green_verdict_passes(self) -> None:
        decision = check_model_swap(
            "deepseek-v4-pro", "deepseek-v4-flash", [_verdict()]
        )
        assert decision.allowed is True
        assert decision.reasons == []

    def test_swap_with_regression_verdict_is_blocked(self) -> None:
        decision = check_model_swap(
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            [_verdict(verdict="REGRESSION")],
        )
        assert decision.allowed is False

    def test_verdict_must_match_route(self) -> None:
        decision = check_model_swap(
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            [_verdict(route="saimon.verify")],
            route="saimon.generate",
        )
        assert decision.allowed is False


class TestRoutingGate:
    def test_gate_routes_blocks_unrecorded_flip(self) -> None:
        current = {"saimon.generate": "deepseek-v4-flash"}
        incumbents = {"saimon.generate": "deepseek-v4-pro"}
        decision = gate_routes(current, incumbents, [])
        assert decision.allowed is False
        assert decision.reasons

    def test_gate_routes_allows_recorded_flip(self) -> None:
        current = {"saimon.generate": "deepseek-v4-flash"}
        incumbents = {"saimon.generate": "deepseek-v4-pro"}
        decision = gate_routes(current, incumbents, [_verdict()])
        assert decision.allowed is True

    def test_gate_routes_allows_no_changes(self) -> None:
        current = {"saimon.generate": "deepseek-v4-pro"}
        incumbents = {"saimon.generate": "deepseek-v4-pro"}
        decision = gate_routes(current, incumbents, [])
        assert decision.allowed is True


class TestVerdictDoc:
    def test_verdict_doc_has_incumbents_and_verdicts(self) -> None:
        doc = load_verdict_doc()
        assert isinstance(doc.get("incumbents"), dict)
        assert isinstance(doc.get("verdicts"), list)

    def test_verdict_doc_incumbents_match_current_routing(self) -> None:
        doc = load_verdict_doc()
        incumbents = doc["incumbents"]
        for route in SAIMON_ROUTES:
            assert incumbents[route] == model_routing.model_for_route(route)


class TestPerTierFixtures:
    def test_every_model_routing_tier_has_committed_fixtures(self) -> None:
        suites = set(fixtures_mod.list_suites("fixtures"))
        for tier in MODEL_ROUTING_TIERS:
            assert tier in suites, f"missing committed fixture suite: {tier}"

    def test_each_tier_fixture_set_is_non_empty(self) -> None:
        for tier in MODEL_ROUTING_TIERS:
            golden = fixtures_mod.load_fixtures("fixtures", tier)
            assert golden, f"no committed golden fixtures for tier {tier!r}"
