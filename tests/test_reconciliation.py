"""Tests for the reconciliation engine (slice #70).

The engine is pure logic over citator treatment codes and brief-citation usage
windows — no network I/O.  Each of the six classification states is exercised
with recorded fixtures, and the treatment-code mapping and disagreement
detection are covered separately.
"""

from __future__ import annotations

import pytest

from plugins.legal import fixtures as legal_fixtures
from plugins.legal.reconcile import (
    CITATOR_RED,
    MARKET_RED,
    NEGATIVE,
    NEUTRAL,
    POSITIVE,
    RESURRECTION,
    STRONG_GREEN,
    WEAK_GREEN,
    YELLOW,
    Classification,
    build_usage_signal,
    canonical_treatment,
    classify,
    detect_disagreements,
)

# ---------------------------------------------------------------------------
# treatment-code mapping
# ---------------------------------------------------------------------------


class TestCanonicalTreatment:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("followed", POSITIVE),
            ("cited", POSITIVE),
            ("green", POSITIVE),
            ("distinguished", NEUTRAL),
            ("questioned", NEUTRAL),
            ("yellow", NEUTRAL),
            ("overruled", NEGATIVE),
            ("red", NEGATIVE),
            ("abrogated", NEGATIVE),
        ],
    )
    def test_known_codes_map_to_canonical(self, code, expected):
        assert canonical_treatment(code) == expected

    def test_normalises_case_and_whitespace(self):
        assert canonical_treatment("  Followed ") == POSITIVE
        assert canonical_treatment("OVERRULED") == NEGATIVE

    def test_unknown_code_falls_back_to_neutral(self):
        assert canonical_treatment("some-future-code") == NEUTRAL

    def test_every_fixture_code_maps_to_a_canonical_value(self):
        canonicals = {POSITIVE, NEUTRAL, NEGATIVE}
        for fixture in legal_fixtures.CLASSIFICATION_FIXTURES.values():
            for code in fixture["citators"].values():
                assert canonical_treatment(code) in canonicals


# ---------------------------------------------------------------------------
# disagreement detection
# ---------------------------------------------------------------------------


class TestDetectDisagreements:
    def test_no_disagreement_when_all_agree(self):
        entries = [
            {"source": "shepards", "treatment": "followed"},
            {"source": "keycite", "treatment": "positive"},
        ]
        assert detect_disagreements(entries) == []

    def test_directional_disagreement_reports_source_pair(self):
        entries = [
            {"source": "shepards", "treatment": "followed"},
            {"source": "keycite", "treatment": "overruled"},
        ]
        disagreements = detect_disagreements(entries)
        assert len(disagreements) == 1
        d = disagreements[0]
        assert {d.source_a, d.source_b} == {"shepards", "keycite"}
        assert {d.treatment_a, d.treatment_b} == {POSITIVE, NEGATIVE}

    def test_output_is_deterministic(self):
        entries = [
            {"source": "keycite", "treatment": "overruled"},
            {"source": "shepards", "treatment": "followed"},
        ]
        first = detect_disagreements(entries)
        second = detect_disagreements(list(reversed(entries)))
        assert first == second

    def test_neutral_vs_positive_is_a_disagreement(self):
        entries = [
            {"source": "shepards", "treatment": "followed"},
            {"source": "bcite", "treatment": "questioned"},
        ]
        disagreements = detect_disagreements(entries)
        assert len(disagreements) == 1
        d = disagreements[0]
        assert d.source_a == "bcite"
        assert d.source_b == "shepards"
        assert d.treatment_a == NEUTRAL
        assert d.treatment_b == POSITIVE


# ---------------------------------------------------------------------------
# usage signal
# ---------------------------------------------------------------------------


class TestBuildUsageSignal:
    def test_active_when_recent_citations(self):
        signal = build_usage_signal({"3m": 5, "6m": 9, "12m": 15, "24m": 30})
        assert signal["active"] is True
        assert signal["declining"] is False
        assert signal["stale"] is False

    def test_declining_when_only_older_citations(self):
        signal = build_usage_signal({"3m": 0, "6m": 4, "12m": 10, "24m": 20})
        assert signal["active"] is False
        assert signal["declining"] is True
        assert signal["stale"] is False

    def test_stale_when_no_citations_in_24_months(self):
        signal = build_usage_signal({"3m": 0, "6m": 0, "12m": 0, "24m": 0})
        assert signal["active"] is False
        assert signal["declining"] is False
        assert signal["stale"] is True

    def test_windows_are_normalised_and_monotonic(self):
        signal = build_usage_signal({"3m": 8, "6m": 2, "12m": 0, "24m": 0})
        assert signal["windows"] == {"3m": 8, "6m": 8, "12m": 8, "24m": 8}

    def test_missing_windows_default_to_zero(self):
        signal = build_usage_signal({})
        assert signal["windows"] == {"3m": 0, "6m": 0, "12m": 0, "24m": 0}
        assert signal["stale"] is True


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


class TestClassify:
    @pytest.mark.parametrize(
        "state",
        [
            STRONG_GREEN,
            WEAK_GREEN,
            YELLOW,
            CITATOR_RED,
            MARKET_RED,
            RESURRECTION,
        ],
    )
    def test_each_state_reachable_from_fixture(self, state):
        fixture = legal_fixtures.CLASSIFICATION_FIXTURES[state]
        signal = build_usage_signal(fixture["usage"])
        result = classify(fixture["citators"], signal)
        assert isinstance(result, Classification)
        assert result.state == state

    def test_strong_green_consensus_positive(self):
        fixture = legal_fixtures.CLASSIFICATION_FIXTURES[STRONG_GREEN]
        result = classify(fixture["citators"], build_usage_signal(fixture["usage"]))
        assert result.consensus == POSITIVE
        assert result.disagreements == []

    def test_yellow_reports_directional_disagreement(self):
        fixture = legal_fixtures.CLASSIFICATION_FIXTURES[YELLOW]
        result = classify(fixture["citators"], build_usage_signal(fixture["usage"]))
        assert result.consensus == "MIXED"
        all_treatments = set()
        for disagreement in result.disagreements:
            all_treatments.add(disagreement.treatment_a)
            all_treatments.add(disagreement.treatment_b)
        assert NEGATIVE in all_treatments
        assert POSITIVE in all_treatments

    def test_manual_check_market_red(self):
        # Positive citators but zero brief usage across the full 24-month window.
        result = classify(
            {"shepards": "followed", "keycite": "positive"},
            build_usage_signal({"3m": 0, "6m": 0, "12m": 0, "24m": 0}),
        )
        assert result.state == MARKET_RED

    def test_manual_check_strong_green(self):
        result = classify(
            {"shepards": "followed", "keycite": "positive", "bcite": "cited"},
            build_usage_signal({"3m": 4, "6m": 9, "12m": 18, "24m": 40}),
        )
        assert result.state == STRONG_GREEN

    def test_empty_citator_map_is_uncertain_not_a_crash(self):
        result = classify(
            {}, build_usage_signal({"3m": 1, "6m": 1, "12m": 1, "24m": 1})
        )
        assert result.state == YELLOW
        assert result.consensus == NEUTRAL
