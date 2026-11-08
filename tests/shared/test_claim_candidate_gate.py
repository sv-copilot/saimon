"""Deterministic claim gate (SAIMON-CLAIM-CANDIDATE-GATE-1).

The model phrases claims; this gate decides whether a sentence is one at all,
and says why. These tests pin the rule table, not the model.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from research_shared.claims import (
    DEFAULT_ACCEPT_THRESHOLD,
    is_claim_candidate,
    looks_like_name_list,
    score_claim_candidate,
)


class TestScoring:
    def test_numeric_claim_scores_high(self):
        score, reasons = score_claim_candidate(
            "The service handled 1,200 requests per minute during the load test."
        )
        assert score >= 1.0
        assert any("numeric" in r.lower() for r in reasons)
        assert any("unit" in r.lower() for r in reasons)

    def test_qualitative_claim_clears_the_threshold(self):
        score, _ = score_claim_candidate(
            "Operators report that reconciliation takes six hours each week."
        )
        assert score >= DEFAULT_ACCEPT_THRESHOLD

    def test_name_list_scores_below_zero(self):
        score, reasons = score_claim_candidate("Smith, Jones, Alvarez, Chen")
        assert score < 0
        assert any("name list" in r.lower() for r in reasons)

    def test_noise_section_scores_negative(self):
        score, reasons = score_claim_candidate("References")
        assert score <= -1.0
        assert any("noise" in r.lower() or "structural" in r.lower() for r in reasons)

    def test_table_of_contents_line_is_rejected(self):
        score, reasons = score_claim_candidate("Chapter ........ 42")
        assert score < DEFAULT_ACCEPT_THRESHOLD
        assert any("dot leader" in r.lower() for r in reasons)

    def test_bare_number_is_rejected(self):
        assert not is_claim_candidate("17")

    def test_lowercase_start_is_penalised(self):
        proper, _ = score_claim_candidate(
            "The tool handled 40 requests per second in the test."
        )
        fragment, _ = score_claim_candidate(
            "the tool handled 40 requests per second in the test."
        )
        assert proper > fragment

    def test_empty_candidate(self):
        score, reasons = score_claim_candidate("   ")
        assert score == 0.0
        assert reasons == ["Empty candidate"]

    def test_reasons_are_never_empty_for_a_scored_candidate(self):
        _, reasons = score_claim_candidate("Revenue grew 12% in 2024.")
        assert reasons


class TestNameList:
    @pytest.mark.parametrize(
        "text",
        ["Smith, Jones", "A. Smith, B. Jones, C. Alvarez", "Jane Doe, John Roe"],
    )
    def test_detects_name_lists(self, text):
        assert looks_like_name_list(text)

    @pytest.mark.parametrize(
        "text",
        ["Costs rose 12%, driven by fuel.", "Revenue was $4.2m in 2024.", "No commas here."],
    )
    def test_does_not_flag_claims(self, text):
        assert not looks_like_name_list(text)


class TestExtractionGate:
    def test_below_threshold_candidates_are_dropped_with_reasons(self, monkeypatch):
        payload = {
            "claims": [
                {"claim_text": "Revenue grew 12% in 2024.", "topic": "growth",
                 "confidence_0_1": 0.9, "rationale": "numeric"},
                {"claim_text": "References", "topic": "noise",
                 "confidence_0_1": 0.9, "rationale": "heading"},
            ]
        }

        class _LLM:
            def call(self, messages):
                return json.dumps(payload)

        class _Resolved:
            llm = _LLM()
            reason = None

        import saimon_mcp.crew.claim_extract as ce

        monkeypatch.setattr(ce, "make_crew_llm", lambda route: _Resolved())
        out = asyncio.run(ce.run_extract_claims("some source text", max_claims=5))
        texts = [c["claim_text"] for c in out]
        assert "Revenue grew 12% in 2024." in texts
        assert "References" not in texts
        assert all("score" in c and "reasons" in c for c in out)
