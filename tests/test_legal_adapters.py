"""Tests for the legal source adapters + content types (slice #72).

The legal plugin registers four S-tier ``SourceIndexAdapter`` adapters
(CourtListener, RECAP, Caselaw Access, SCOTUS Merits) and five legal content
types.  These tests use recorded fixture responses and run without live
credentials: a missing API key must yield a ``missing_config`` readiness, never
a crash.
"""

from __future__ import annotations

import pytest

from plugins.legal import LegalPlugin
from plugins.legal.adapters import (
    CaselawAccessAdapter,
    CourtListenerAdapter,
    RecapAdapter,
    ScotusMeritsAdapter,
)
from plugins.legal.adapters.caselaw_access import parse_caselaw_results
from plugins.legal.adapters.courtlistener import parse_courtlistener_results
from plugins.legal.adapters.recap import parse_recap_results
from plugins.legal.adapters.scotus_merits import parse_scotus_results
from plugins.legal.content_types import CONTENT_TYPES
from research_shared.adapters.base import SourceIndexAdapter

# ---------------------------------------------------------------------------
# recorded fixtures (no live credentials required)
# ---------------------------------------------------------------------------

COURTLISTENER_FIXTURE = {
    "results": [
        {
            "id": 2812209,
            "name": "Roe v. Wade",
            "date_filed": "1973-01-22",
            "citation": "410 U.S. 113",
            "court": "scotus",
        }
    ]
}

RECAP_FIXTURE = {
    "results": [
        {
            "id": 456,
            "document_number": "1",
            "description": "Complaint",
            "date_filed": "2020-01-15",
            "docket_entry": 1,
        }
    ]
}

CASELAW_FIXTURE = {
    "results": [
        {
            "id": 789,
            "name": "Brown v. Board of Education",
            "decision_date": "1954-05-17",
            "court": {"name": "Supreme Court of the United States"},
            "jurisdiction": {"name": "United States"},
        }
    ]
}

SCOTUS_FIXTURE = {
    "results": [
        {
            "id": 321,
            "case_name": "Obergefell v. Hodges",
            "docket_number": "14-556",
            "term": 2014,
        }
    ]
}


# ---------------------------------------------------------------------------
# adapter protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter",
    [
        CourtListenerAdapter(),
        RecapAdapter(),
        CaselawAccessAdapter(),
        ScotusMeritsAdapter(),
    ],
)
class TestAdapterProtocol:
    def test_satisfies_source_index_adapter(self, adapter):
        assert isinstance(adapter, SourceIndexAdapter)

    def test_tier_is_s(self, adapter):
        assert adapter.tier == "S"

    def test_has_name_and_trust_model(self, adapter):
        assert adapter.name
        assert adapter.trust_model


# ---------------------------------------------------------------------------
# readiness (missing_config, never a crash)
# ---------------------------------------------------------------------------


class TestReadiness:
    def test_courtlistener_missing_config_without_key(self, monkeypatch):
        monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
        adapter = CourtListenerAdapter(api_key=None)
        assert adapter.readiness()["status"] == "missing_config"

    def test_courtlistener_ready_with_key(self):
        adapter = CourtListenerAdapter(api_key="test-key")
        assert adapter.readiness()["status"] == "ready"

    def test_recap_falls_back_to_courtlistener_key(self, monkeypatch):
        monkeypatch.delenv("RECAP_API_KEY", raising=False)
        monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
        adapter = RecapAdapter(api_key=None)
        assert adapter.readiness()["status"] == "missing_config"

    def test_caselaw_missing_config_without_key(self, monkeypatch):
        monkeypatch.delenv("CASELAW_ACCESS_API_KEY", raising=False)
        adapter = CaselawAccessAdapter(api_key=None)
        assert adapter.readiness()["status"] == "missing_config"

    def test_scotus_ready_without_key(self, monkeypatch):
        monkeypatch.delenv("SCOTUS_API_KEY", raising=False)
        adapter = ScotusMeritsAdapter(api_key=None)
        # SCOTUS merits briefs are public — no key required.
        assert adapter.readiness()["status"] == "ready"

    def test_plugin_reports_missing_config_when_keys_absent(self, monkeypatch):
        monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
        monkeypatch.delenv("RECAP_API_KEY", raising=False)
        monkeypatch.delenv("CASELAW_ACCESS_API_KEY", raising=False)
        assert LegalPlugin().readiness()["status"] == "missing_config"


# ---------------------------------------------------------------------------
# search without credentials returns [] (no crash)
# ---------------------------------------------------------------------------


class TestSearchWithoutCredentials:
    @pytest.mark.parametrize(
        "adapter",
        [
            CourtListenerAdapter(api_key=None),
            RecapAdapter(api_key=None),
            CaselawAccessAdapter(api_key=None),
            ScotusMeritsAdapter(api_key=None),
        ],
    )
    async def test_search_returns_empty(self, adapter):
        results = await adapter.search("roe v wade")
        assert results == []


# ---------------------------------------------------------------------------
# recorded-response parsing
# ---------------------------------------------------------------------------


class TestRecordedResponseParsing:
    def test_parse_courtlistener_results(self):
        results = parse_courtlistener_results(COURTLISTENER_FIXTURE)
        assert len(results) == 1
        result = results[0]
        assert result.title == "Roe v. Wade"
        assert result.year == 1973
        assert result.source_index == "courtlistener"
        assert result.identifier == "cl:2812209"

    def test_parse_recap_results(self):
        results = parse_recap_results(RECAP_FIXTURE)
        assert len(results) == 1
        assert results[0].title == "Complaint"
        assert results[0].source_index == "recap"
        assert results[0].year == 2020

    def test_parse_caselaw_results(self):
        results = parse_caselaw_results(CASELAW_FIXTURE)
        assert len(results) == 1
        assert results[0].title == "Brown v. Board of Education"
        assert results[0].year == 1954
        assert results[0].source_index == "caselaw_access"

    def test_parse_scotus_results(self):
        results = parse_scotus_results(SCOTUS_FIXTURE)
        assert len(results) == 1
        assert results[0].title == "Obergefell v. Hodges"
        assert results[0].source_index == "scotus_merits"
        assert results[0].year == 2014


# ---------------------------------------------------------------------------
# content types
# ---------------------------------------------------------------------------


class TestContentTypes:
    def test_six_content_types(self):
        assert len(CONTENT_TYPES) == 6

    def test_all_namespaced_legal(self):
        for ct in CONTENT_TYPES:
            assert ct["name"].startswith("legal:")

    def test_required_fields_present(self):
        for ct in CONTENT_TYPES:
            assert ct["name"]
            assert ct["description"]
            assert "required_params" in ct


class TestPluginRegistration:
    def test_plugin_registers_four_adapters(self):
        adapters = LegalPlugin().adapters()
        assert len(adapters) == 4

    def test_plugin_registers_six_content_types(self):
        content_types = LegalPlugin().content_types()
        assert len(content_types) == 6

    def test_adapters_package_exports(self):
        from plugins.legal import adapters as adapters_pkg

        for name in (
            "CourtListenerAdapter",
            "RecapAdapter",
            "CaselawAccessAdapter",
            "ScotusMeritsAdapter",
        ):
            assert hasattr(adapters_pkg, name)


class TestAdapterExtra:
    def test_parser_handles_empty_payload(self):
        assert parse_courtlistener_results({"results": []}) == []
        assert parse_recap_results({}) == []
        assert parse_caselaw_results({"results": []}) == []
        assert parse_scotus_results({}) == []
