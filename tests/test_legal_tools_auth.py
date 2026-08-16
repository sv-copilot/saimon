"""Tests for the legal authority tools (slice #74).

Legal tools 4-6: ``rank_persuasive_authority`` (search + weighting),
``build_authority_ladder`` (search + weighting + generate), and
``detect_split_of_authority`` (search + generate).  Pure glue over the #71
weighting model — no network I/O.
"""

from __future__ import annotations

import pytest

from plugins.legal import LegalPlugin
from plugins.legal.tools.authority_ladder import build_authority_ladder
from plugins.legal.tools.rank_authority import rank_persuasive_authority
from plugins.legal.tools.split_of_authority import detect_split_of_authority
from plugins.legal.weighting import (
    persuasive_authority,
    persuasive_authority_breakdown,
)
from research_shared.domain_plugin import DomainTool

# A strong, recent, high-density case for fixture use.
CASE = {
    "id": "case-1",
    "title": "Smith v. Jones",
    "metadata": {
        "citation_string": "410 U.S. 113",
        "court": "Supreme Court of the United States",
        "decided_date": "2026-01-01",
        "citation_count": 100,
        "subject": "qualified immunity",
    },
}

CONTEXT = {
    "target_jurisdiction": "federal",
    "issue": "qualified immunity",
    "reconciliation": {"state": "STRONG_GREEN"},
}


# ---------------------------------------------------------------------------
# rank_persuasive_authority
# ---------------------------------------------------------------------------


class TestRankPersuasiveAuthority:
    def test_returns_score_and_breakdown(self):
        result = rank_persuasive_authority(CASE, CONTEXT)
        assert 0.0 <= result["score"] <= 1.0
        factors = result["breakdown"]
        assert {f["factor"] for f in factors} == {
            "hierarchy",
            "density",
            "recency",
            "fit",
            "treatment",
        }

    def test_breakdown_contributions_sum_to_score(self):
        result = rank_persuasive_authority(CASE, CONTEXT)
        total = sum(f["contribution"] for f in result["breakdown"])
        assert total == pytest.approx(result["score"], abs=0.001)

    def test_matches_weighting_model(self):
        result = rank_persuasive_authority(CASE, CONTEXT)
        assert result["score"] == pytest.approx(persuasive_authority(CASE, CONTEXT))


# ---------------------------------------------------------------------------
# build_authority_ladder
# ---------------------------------------------------------------------------


class TestBuildAuthorityLadder:
    def test_orders_strongest_first(self):
        weak_case = {
            **CASE,
            "metadata": {
                **CASE["metadata"],
                "court": "Unknown Court",
                "citation_count": 0,
                "decided_date": "1950-01-01",
            },
        }
        result = build_authority_ladder([weak_case, CASE], CONTEXT)
        scores = [r["score"] for r in result["ladder"]]
        assert scores == sorted(scores, reverse=True)
        assert result["ladder"][0]["citation"] != weak_case["id"]

    def test_includes_reasoning_and_memo(self):
        result = build_authority_ladder([CASE], CONTEXT)
        assert result["ladder"]
        assert result["ladder"][0]["reasoning"]
        assert result["memo"]


# ---------------------------------------------------------------------------
# detect_split_of_authority
# ---------------------------------------------------------------------------


class TestDetectSplitOfAuthority:
    def test_reports_circuit_positions_and_split(self):
        cases = [
            {
                "metadata": {
                    "court": ("United States Court of Appeals for the Ninth Circuit"),
                    "position": "for",
                }
            },
            {
                "metadata": {
                    "court": ("United States Court of Appeals for the Ninth Circuit"),
                    "position": "for",
                }
            },
            {
                "metadata": {
                    "court": ("United States Court of Appeals for the Fifth Circuit"),
                    "position": "against",
                }
            },
        ]
        result = detect_split_of_authority(cases)
        assert result["split"] is True
        assert "Ninth Circuit" in result["circuits"]
        assert result["circuits"]["Ninth Circuit"]["positions"] == ["for"]
        assert result["circuits"]["Fifth Circuit"]["positions"] == ["against"]

    def test_no_split_when_all_agree(self):
        cases = [
            {
                "metadata": {
                    "court": ("United States Court of Appeals for the Ninth Circuit"),
                    "position": "for",
                }
            },
            {
                "metadata": {
                    "court": ("United States Court of Appeals for the Fifth Circuit"),
                    "position": "for",
                }
            },
        ]
        result = detect_split_of_authority(cases)
        assert result["split"] is False


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_tools_registered(self):
        names = [tool.name for tool in LegalPlugin().tools()]
        assert "legal.rank_persuasive_authority" in names
        assert "legal.build_authority_ladder" in names
        assert "legal.detect_split_of_authority" in names

    def test_all_tools_are_domain_tools(self):
        for tool in LegalPlugin().tools():
            assert isinstance(tool, DomainTool)


# ---------------------------------------------------------------------------
# weighting-model breakdown consistency
# ---------------------------------------------------------------------------


class TestBreakdownConsistency:
    def test_breakdown_score_matches_model(self):
        breakdown = persuasive_authority_breakdown(CASE, CONTEXT)
        assert breakdown["score"] == pytest.approx(persuasive_authority(CASE, CONTEXT))
        assert sum(breakdown["weights"].values()) == pytest.approx(1.0)
