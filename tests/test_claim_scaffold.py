"""Tests for the claim-elements scaffolder (SAIMON-LEGAL-CLAIM-SCAFFOLD-1).

``legal.scaffold_claim`` is the retail legal bridge from "is the law on our
side" to "how good is our position."  Given a claim type, a target
jurisdiction, and the client's facts, it enumerates the claim's elements and,
for each element:

- ranks the strongest authority via ``build_authority_ladder`` +
  ``rank_persuasive_authority`` (with confidence),
- flags a circuit split via ``detect_split_of_authority``,
- flags elements that are factually weak given the client's facts.

The composed core-MCP building blocks (generate/rank/split/verify) are all
deterministic here, so every test runs against recorded fixture authorities
with no network I/O.
"""

from __future__ import annotations

import pytest

from plugins.legal import LegalPlugin
from plugins.legal.tools.scaffold_claim import ScaffoldClaimTool, scaffold_claim
from research_shared.domain_plugin import DomainTool

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

CLAIM_TYPE_KEYS = [
    "dtsa_misappropriation",
    "state_trade_secret",
    "cfaa",
    "tortious_interference",
]

DTSA_FIRST_ELEMENT = "Existence of a trade secret"

STRONG_FACTS = {
    "facts": {
        "trade_secret_identified": True,
        "reasonable_measures": True,
        "improper_acquisition": True,
        "use_or_disclosure": True,
        "commerce_nexus": True,
        "actual_loss": True,
    }
}

WEAK_FACTS = {
    "facts": {
        "trade_secret_identified": True,
        "reasonable_measures": False,  # client took no secrecy measures
        "improper_acquisition": True,
        "use_or_disclosure": True,
        "commerce_nexus": True,
        "actual_loss": True,
    }
}


# ---------------------------------------------------------------------------
# element enumeration
# ---------------------------------------------------------------------------


class TestElementEnumeration:
    def test_dtsa_enumerates_at_least_three_elements(self):
        result = scaffold_claim("dtsa_misappropriation", "federal", STRONG_FACTS)
        assert result["element_count"] >= 3
        assert len(result["elements"]) >= 3
        assert result["elements"][0]["element"] == DTSA_FIRST_ELEMENT

    @pytest.mark.parametrize("claim_type", CLAIM_TYPE_KEYS)
    def test_each_claim_type_enumerates_at_least_three_elements(self, claim_type):
        result = scaffold_claim(claim_type)
        assert result["element_count"] >= 3
        assert len(result["elements"]) >= 3

    def test_unknown_claim_type_raises(self):
        with pytest.raises(ValueError):
            scaffold_claim("not_a_real_claim")


# ---------------------------------------------------------------------------
# authority ranking + split flag
# ---------------------------------------------------------------------------


class TestAuthorityAndSplit:
    def test_each_element_carries_ranked_authority_with_confidence(self):
        result = scaffold_claim("dtsa_misappropriation", "federal", STRONG_FACTS)
        for element in result["elements"]:
            authority = element["authority"]
            assert authority is not None
            assert authority["citation"]
            assert 0.0 <= authority["score"] <= 1.0
            assert 0.0 <= authority["confidence"] <= 1.0
            assert authority["reasoning"]
            assert isinstance(element["split"], bool)
            assert "split_summary" in element

    def test_strongest_authority_is_top_of_ladder(self):
        result = scaffold_claim("dtsa_misappropriation", "federal", STRONG_FACTS)
        for element in result["elements"]:
            ladder = element["ladder"]
            assert ladder, f"no ladder for {element['element']}"
            scores = [r["score"] for r in ladder]
            assert scores == sorted(scores, reverse=True)
            assert element["authority"]["citation"] == ladder[0]["citation"]


# ---------------------------------------------------------------------------
# weakness flag from client facts
# ---------------------------------------------------------------------------


class TestWeaknessFlag:
    def test_weak_facts_flag_at_least_one_element(self):
        result = scaffold_claim("dtsa_misappropriation", "federal", WEAK_FACTS)
        assert result["weak_elements"], "expected at least one weak element"
        assert DTSA_FIRST_ELEMENT in result["weak_elements"]
        weak = next(
            e for e in result["elements"] if e["element"] == DTSA_FIRST_ELEMENT
        )
        assert weak["weak"] is True
        assert weak["weak_reasons"]

    def test_strong_facts_flag_no_elements(self):
        result = scaffold_claim("dtsa_misappropriation", "federal", STRONG_FACTS)
        assert result["weak_elements"] == []



# ---------------------------------------------------------------------------
# verified / annotated memo
# ---------------------------------------------------------------------------


class TestVerifiedMemo:
    def test_memo_is_annotated_and_verified(self):
        result = scaffold_claim("dtsa_misappropriation", "federal", WEAK_FACTS)
        assert result["verification"]["verified"] is True
        assert result["verification"]["annotations"]
        memo = result["memo"]
        assert memo
        assert DTSA_FIRST_ELEMENT in memo
        for element in result["elements"]:
            assert element["element"] in memo


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_tool_registered_on_plugin(self):
        names = [tool.name for tool in LegalPlugin().tools()]
        assert "legal.scaffold_claim" in names

    def test_tool_is_a_domain_tool(self):
        tool = ScaffoldClaimTool()
        assert isinstance(tool, DomainTool)
        assert tool.name == "legal.scaffold_claim"
        assert tool.description
        assert isinstance(tool.input_schema, dict)

    async def test_execute_through_tool(self):
        tool = ScaffoldClaimTool()
        result = await tool.execute(
            {
                "claim_type": "dtsa_misappropriation",
                "jurisdiction": "federal",
                "client_facts": STRONG_FACTS,
            }
        )
        assert result["element_count"] >= 3


# ---------------------------------------------------------------------------
# callable via domain-mcp
# ---------------------------------------------------------------------------


class TestDomainMcpRouting:
    def test_scaffold_claim_routes_through_domain_mcp(self, monkeypatch):
        monkeypatch.setenv("SAIMON_API_KEY", "sk-test-domain-key")
        monkeypatch.setenv("SAIMON_DOMAIN_PLUGIN_PATHS", "")
        import sys

        sys.modules.pop("saimon_mcp.domain.server", None)
        from fastapi.testclient import TestClient

        from saimon_mcp.domain import server as srv

        loaded = srv._load_plugins(["plugins.legal"])
        assert "legal" in loaded

        client = TestClient(srv.app)
        response = client.post(
            "/tools/call",
            json={
                "trace_id": "00000000-0000-0000-0000-0000000001c5",
                "content_type": "domain",
                "parameters": {
                    "tool": "legal.scaffold_claim",
                    "arguments": {
                        "claim_type": "dtsa_misappropriation",
                        "jurisdiction": "federal",
                        "client_facts": STRONG_FACTS,
                    },
                },
            },
            headers={"X-Saimon-API-Key": "sk-test-domain-key"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["element_count"] >= 3

