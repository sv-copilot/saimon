"""Tests for the legal domain tools (slice #73).

The first three legal tools are pure glue over the reconciliation engine
(#70) and adapters (#72): ``parse_citation`` (normalize), ``reconcile_citators``
(diff citators), and ``detect_implicit_overruling`` (green-citator cases that
briefs stopped citing).  No network I/O — every test uses recorded fixtures.
"""

from __future__ import annotations

import pytest

from plugins.legal import LegalPlugin
from plugins.legal import fixtures as legal_fixtures
from plugins.legal.tools.detect_implicit_overruling import (
    DetectImplicitOverrulingTool,
    detect_implicit_overruling,
)
from plugins.legal.tools.parse_citation import ParseCitationTool, parse_citation
from plugins.legal.tools.reconcile_citators import (
    ReconcileCitatorsTool,
    reconcile_citators,
)
from research_shared.domain_plugin import DomainTool

# ---------------------------------------------------------------------------
# parse_citation
# ---------------------------------------------------------------------------


class TestParseCitation:
    def test_bluebook_format(self):
        result = parse_citation("Roe v. Wade, 410 U.S. 113 (1973)")
        assert result["format"] == "bluebook"
        assert result["volume"] == "410"
        assert result["reporter"] == "U.S."
        assert result["page"] == "113"
        assert result["year"] == 1973

    def test_neutral_format(self):
        result = parse_citation("[2020] UKSC 1")
        assert result["format"] == "neutral"
        assert result["year"] == 2020
        assert result["court"] == "UKSC"
        assert result["number"] == "1"

    def test_courtlistener_url_format(self):
        result = parse_citation(
            "https://www.courtlistener.com/opinion/2812209/roe-v-wade/"
        )
        assert result["format"] == "courtlistener_url"
        assert result["case_id"] == "2812209"

    def test_canonical_is_normalised(self):
        assert parse_citation("410 U.S. 113")["canonical"] == "410 U.S. 113"
        assert parse_citation("[2020] UKSC 1")["canonical"] == "[2020] UKSC 1"
        assert (
            parse_citation("https://www.courtlistener.com/opinion/2812209/roe-v-wade/")[
                "canonical"
            ]
            == "courtlistener:2812209"
        )

    def test_unparseable_falls_back_to_unknown(self):
        result = parse_citation("some unparseable string")
        assert result["format"] == "unknown"

    def test_missing_citation_raises(self):
        with pytest.raises(ValueError):
            parse_citation("")


# ---------------------------------------------------------------------------
# reconcile_citators
# ---------------------------------------------------------------------------


class TestReconcileCitators:
    def test_returns_consensus_and_classification(self):
        result = reconcile_citators(
            "410 U.S. 113",
            {"shepards": "followed", "keycite": "followed"},
            {"3m": 12, "6m": 25, "12m": 48, "24m": 90},
        )
        assert result["consensus"] == "POSITIVE"
        assert result["classification"] == "STRONG_GREEN"

    def test_reports_disagreements(self):
        result = reconcile_citators(
            "410 U.S. 113",
            {"shepards": "followed", "keycite": "overruled"},
            {"3m": 0, "6m": 0, "12m": 0, "24m": 0},
        )
        assert result["consensus"] == "MIXED"
        assert result["classification"] == "YELLOW"
        assert len(result["disagreements"]) >= 1

    def test_includes_usage_signal(self):
        result = reconcile_citators(
            "410 U.S. 113",
            {"shepards": "followed", "keycite": "positive"},
            {"3m": 0, "6m": 0, "12m": 0, "24m": 0},
        )
        assert result["usage_signal"]["stale"] is True
        assert result["classification"] == "MARKET_RED"

    def test_all_six_states_reachable_from_fixtures(self):
        for state, fixture in legal_fixtures.CLASSIFICATION_FIXTURES.items():
            result = reconcile_citators(
                "fixture-case", fixture["citators"], fixture["usage"]
            )
            assert result["classification"] == state


# ---------------------------------------------------------------------------
# detect_implicit_overruling
# ---------------------------------------------------------------------------


class TestDetectImplicitOverruling:
    def test_flags_green_case_with_zero_briefs_over_18mo(self):
        result = detect_implicit_overruling(
            "410 U.S. 113",
            {"shepards": "followed", "keycite": "positive"},
            {"3m": 0, "6m": 0, "12m": 0, "18m": 0, "24m": 5},
        )
        assert result["implicitly_overruled"] is True

    def test_does_not_flag_green_case_with_recent_briefs(self):
        result = detect_implicit_overruling(
            "410 U.S. 113",
            {"shepards": "followed", "keycite": "positive"},
            {"3m": 3, "6m": 8, "12m": 15, "24m": 30},
        )
        assert result["implicitly_overruled"] is False

    def test_does_not_flag_non_green_case(self):
        result = detect_implicit_overruling(
            "410 U.S. 113",
            {"shepards": "overruled"},
            {"3m": 0, "6m": 0, "12m": 0, "18m": 0, "24m": 0},
        )
        assert result["implicitly_overruled"] is False


# ---------------------------------------------------------------------------
# DomainTool registration on the legal plugin
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_tools_registered_on_plugin(self):
        names = [tool.name for tool in LegalPlugin().tools()]
        assert "legal.parse_citation" in names
        assert "legal.reconcile_citators" in names
        assert "legal.detect_implicit_overruling" in names

    @pytest.mark.parametrize(
        "tool",
        [
            ParseCitationTool(),
            ReconcileCitatorsTool(),
            DetectImplicitOverrulingTool(),
        ],
    )
    def test_tools_satisfy_domain_tool_protocol(self, tool):
        assert isinstance(tool, DomainTool)
        assert tool.name.startswith("legal.")
        assert tool.description
        assert isinstance(tool.input_schema, dict)

    async def test_execute_through_tool(self):
        tool = ParseCitationTool()
        result = await tool.execute({"citation": "410 U.S. 113"})
        assert result["format"] == "bluebook"


# ---------------------------------------------------------------------------
# callable via domain-mcp
# ---------------------------------------------------------------------------


class TestDomainMcpRouting:
    def test_legal_tool_routes_through_domain_mcp(self, monkeypatch):
        monkeypatch.setenv("SAIMON_API_KEY", "sk-test-domain-key")
        monkeypatch.setenv("SAIMON_DOMAIN_PLUGIN_PATHS", "")
        import sys

        sys.modules.pop("mcp.domain.server", None)
        from fastapi.testclient import TestClient

        from mcp.domain import server as srv

        loaded = srv._load_plugins(["plugins.legal"])
        assert "legal" in loaded

        client = TestClient(srv.app)
        response = client.post(
            "/tools/call",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000073",
                "content_type": "domain",
                "parameters": {
                    "tool": "legal.parse_citation",
                    "arguments": {"citation": "410 U.S. 113"},
                },
            },
            headers={"X-Saimon-API-Key": "sk-test-domain-key"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["format"] == "bluebook"
