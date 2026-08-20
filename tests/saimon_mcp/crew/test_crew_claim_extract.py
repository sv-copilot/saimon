"""Tests for crew.extract_claims@v1 (SAIMON-CREW-CLAIM-EXTRACT-1)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from saimon_mcp.crew.claim_extract import (
    filter_crew_claim_candidates,
    parse_claims,
    run_extract_claims,
)
from saimon_mcp.crew.llm import CrewLLMResolution


class TestFilterQualityGate:
    def test_returns_structured_candidates_with_claim_text_and_confidence_0_1(
        self,
    ) -> None:
        candidates = [
            {
                "claim_text": "Paris is the capital of France.",
                "topic": "geography",
                "confidence_0_1": 0.9,
                "rationale": "verifiable against sources",
            }
        ]
        out = filter_crew_claim_candidates(candidates)
        assert len(out) == 1
        assert out[0]["claim_text"] == "Paris is the capital of France."
        assert 0.0 <= out[0]["confidence_0_1"] <= 1.0

    def test_byline_and_heading_candidates_filtered(self) -> None:
        candidates = [
            {"claim_text": "By Jane Doe", "confidence_0_1": 0.5},
            {"claim_text": "Chapter 1", "confidence_0_1": 0.5},
            {"claim_text": "Table of Contents", "confidence_0_1": 0.5},
            {"claim_text": "The moon orbits the Earth.", "confidence_0_1": 0.8},
        ]
        out = filter_crew_claim_candidates(candidates)
        assert [c["claim_text"] for c in out] == ["The moon orbits the Earth."]

    def test_confidence_clamped_to_0_1(self) -> None:
        candidates = [
            {"claim_text": "A verifiable claim about water boiling.", "confidence_0_1": 99.0},
            {"claim_text": "Another verifiable claim about gravity.", "confidence_0_1": -3},
            {"claim_text": "A third verifiable claim about light speed.", "confidence_0_1": "not-a-number"},
        ]
        out = filter_crew_claim_candidates(candidates)
        assert out[0]["confidence_0_1"] == 1.0
        assert out[1]["confidence_0_1"] == 0.0
        assert out[2]["confidence_0_1"] == 0.0


class TestParseClaims:
    def test_malformed_llm_output_never_raises(self) -> None:
        assert parse_claims("not json at all") == []
        assert parse_claims('{"unexpected": "shape"}') == []
        assert parse_claims("") == []

    def test_parses_valid_claims(self) -> None:
        raw = '{"claims": [{"claim_text": "Water boils at 100C at sea level.", "confidence_0_1": 0.95}]}'
        out = parse_claims(raw)
        assert len(out) == 1
        assert out[0]["confidence_0_1"] == 0.95


class TestRunExtractClaims:
    def test_returns_empty_without_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from saimon_mcp.crew import claim_extract

        monkeypatch.setattr(
            claim_extract,
            "make_crew_llm",
            lambda route: CrewLLMResolution(
                None, "crewai import failed: ModuleNotFoundError: No module named 'mcp.shared'"
            ),
        )
        assert asyncio.run(run_extract_claims("some text")) == []

    def test_routes_to_declared_saimon_extract_claims(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#190 — crew.extract_claims@v1 must resolve the declared
        saimon.extract_claims route; never an undeclared crew.* route."""
        from saimon_mcp.crew import claim_extract

        routes: list[str] = []

        def spy(route: str) -> CrewLLMResolution:
            routes.append(route)
            return CrewLLMResolution(MagicMock())

        monkeypatch.setattr(claim_extract, "make_crew_llm", spy)
        assert asyncio.run(run_extract_claims("source text")) == []
        assert routes == ["saimon.extract_claims"]

    def test_extracts_and_filters_via_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from saimon_mcp.crew import claim_extract

        fake_llm = MagicMock()
        fake_llm.call.return_value = (
            '{"claims": ['
            '{"claim_text": "The Earth is round.", "confidence_0_1": 0.99},'
            '{"claim_text": "Chapter 2", "confidence_0_1": 0.5}'
            "]}"
        )
        monkeypatch.setattr(
            claim_extract,
            "make_crew_llm",
            lambda route: CrewLLMResolution(fake_llm),
        )
        out = asyncio.run(run_extract_claims("source text"))
        assert [c["claim_text"] for c in out] == ["The Earth is round."]
