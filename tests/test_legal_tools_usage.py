"""Tests for the legal usage tools (slice #75).

Legal tools 7-10: ``map_doctrine_diffusion`` (search + generate),
``predict_erie_guess`` (search + verify + weighting),
``extract_procedural_history`` (search + generate), and ``build_usage_layer``
(search).  Pure glue over the reconciliation engine (#70), weighting model
(#71), adapters (#72), and the #73 tools — no network I/O.
"""

from __future__ import annotations

from plugins.legal import LegalPlugin
from plugins.legal.tools.doctrine_diffusion import map_doctrine_diffusion
from plugins.legal.tools.erie_guess import predict_erie_guess
from plugins.legal.tools.procedural_history import extract_procedural_history
from plugins.legal.tools.usage_layer import build_usage_layer
from research_shared.domain_plugin import DomainTool

# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

STRONG_CASE = {
    "id": "case-strong",
    "title": "Smith v. Jones",
    "metadata": {
        "citation_string": "410 U.S. 113",
        "court": "Supreme Court of the United States",
        "decided_date": "2025-01-01",
        "citation_count": 100,
        "subject": "qualified immunity",
    },
}

WEAK_CASE = {
    "id": "case-weak",
    "title": "Doe v. Roe",
    "metadata": {
        "citation_string": "99 F.4th 1",
        "court": "Unknown Court",
        "decided_date": "1950-01-01",
        "citation_count": 0,
        "subject": "unrelated topic",
    },
}

ERIE_CONTEXT = {"target_jurisdiction": "federal", "issue": "qualified immunity"}


# ---------------------------------------------------------------------------
# map_doctrine_diffusion
# ---------------------------------------------------------------------------


class TestMapDoctrineDiffusion:
    def test_tracks_adoption_timeline(self):
        cases = [
            {
                "metadata": {
                    "jurisdiction": "California",
                    "decided_date": "2020-01-01",
                }
            },
            {
                "metadata": {
                    "jurisdiction": "Nevada",
                    "decided_date": "2021-01-01",
                }
            },
            {
                "metadata": {
                    "jurisdiction": "California",
                    "decided_date": "2022-01-01",
                }
            },
        ]
        result = map_doctrine_diffusion(cases, doctrine="right of publicity")
        assert result["first_adoption"] == {
            "year": 2020,
            "jurisdiction": "California",
        }
        assert result["jurisdictions"] == ["California", "Nevada"]
        assert [a["year"] for a in result["adoptions"]] == [2020, 2021, 2022]
        assert result["adoptions"][1]["case_count"] == 1
        assert result["years_to_spread"] == 2
        assert "right of publicity" in result["memo"]

    def test_empty_cases(self):
        result = map_doctrine_diffusion([], doctrine="x")
        assert result["first_adoption"] is None
        assert result["jurisdictions"] == []
        assert result["adoptions"] == []


# ---------------------------------------------------------------------------
# predict_erie_guess
# ---------------------------------------------------------------------------


class TestPredictErieGuess:
    def test_returns_prediction_confidence_evidence(self):
        candidates = [
            {"state": "Nevada", "evidence": [WEAK_CASE]},
            {"state": "California", "evidence": [STRONG_CASE]},
        ]
        result = predict_erie_guess(
            "Which state's law governs?", candidates, ERIE_CONTEXT
        )
        assert result["prediction"] == "California"
        assert 0.0 < result["confidence"] <= 1.0
        assert result["evidence"] == ["410 U.S. 113"]
        assert set(result["scores"]) == {"California", "Nevada"}

    def test_single_candidate(self):
        result = predict_erie_guess(
            "Which state's law governs?", [{"state": "Nevada", "evidence": []}]
        )
        assert result["prediction"] == "Nevada"
        assert 0.0 <= result["confidence"] <= 1.0

    def test_no_candidates(self):
        result = predict_erie_guess("Which state's law governs?", [])
        assert result["prediction"] is None
        assert result["confidence"] == 0.0
        assert result["evidence"] == []


# ---------------------------------------------------------------------------
# extract_procedural_history
# ---------------------------------------------------------------------------


class TestExtractProceduralHistory:
    def test_sorts_timeline_and_classifies_stages(self):
        events = [
            {
                "date": "2020-06-01",
                "event": "Notice of appeal filed",
                "court": "Ninth Circuit",
            },
            {
                "date": "2019-01-15",
                "event": "Complaint filed",
                "court": "District Court",
            },
            {
                "date": "2021-03-01",
                "event": "Opinion issued",
                "court": "Ninth Circuit",
            },
        ]
        result = extract_procedural_history(events)
        assert [e["date"] for e in result["timeline"]] == [
            "2019-01-15",
            "2020-06-01",
            "2021-03-01",
        ]
        assert [e["stage"] for e in result["timeline"]] == [
            "filing",
            "appeal",
            "decision",
        ]
        assert result["stages"] == ["filing", "appeal", "decision"]
        assert result["event_count"] == 3
        assert result["summary"]

    def test_empty_events(self):
        result = extract_procedural_history([])
        assert result["timeline"] == []
        assert result["event_count"] == 0


# ---------------------------------------------------------------------------
# build_usage_layer
# ---------------------------------------------------------------------------


class TestBuildUsageLayer:
    def test_computes_opinion_vs_brief_delta(self):
        authorities = [
            {"citation": "A", "brief_citations": 0, "opinion_citations": 5},
            {"citation": "B", "brief_citations": 3, "opinion_citations": 1},
            {"citation": "C", "brief_citations": 2, "opinion_citations": 0},
        ]
        result = build_usage_layer(authorities)
        rows = {row["citation"]: row for row in result["rows"]}
        assert rows["A"]["delta"] == 5
        assert rows["A"]["avoided"] is True
        assert rows["B"]["delta"] == -2
        assert rows["B"]["avoided"] is False
        assert rows["C"]["delta"] == -2
        assert rows["C"]["brief_only"] is True
        assert result["avoided"] == ["A"]
        assert result["avoided_count"] == 1
        assert "1 authority avoided by litigators" in result["headline"]
        assert result["stats"]["total_brief_citations"] == 5
        assert result["stats"]["total_opinion_citations"] == 6

    def test_headline_pluralization(self):
        result = build_usage_layer(
            [
                {"citation": "A", "brief_citations": 0, "opinion_citations": 1},
                {"citation": "B", "brief_citations": 0, "opinion_citations": 1},
            ]
        )
        assert result["avoided_count"] == 2
        assert "2 authorities avoided by litigators" in result["headline"]


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_tools_registered(self):
        names = [tool.name for tool in LegalPlugin().tools()]
        assert "legal.map_doctrine_diffusion" in names
        assert "legal.predict_erie_guess" in names
        assert "legal.extract_procedural_history" in names
        assert "legal.build_usage_layer" in names

    def test_all_ten_tools_returned(self):
        assert len(LegalPlugin().tools()) == 10

    def test_all_tools_are_domain_tools(self):
        for tool in LegalPlugin().tools():
            assert isinstance(tool, DomainTool)
            assert tool.name.startswith("legal.")
            assert tool.description
            assert isinstance(tool.input_schema, dict)


# ---------------------------------------------------------------------------
# ninth-circuit experiment
# ---------------------------------------------------------------------------


class TestNinthCircuitExperiment:
    def test_runs_end_to_end_on_recorded_fixtures(self):
        from plugins.legal.experiments.ninth_circuit import run_experiment

        report = run_experiment()
        assert report["steps_completed"] == 7
        assert "avoided by litigators" in report["headline"]
        assert "not in the opinion graph" in report["memo"]
        assert report["graph"]["edge_count"] > 0
        assert report["classifications"]

    def test_emits_research_memo_with_delta_headline(self):
        from plugins.legal.experiments.ninth_circuit import run_experiment

        report = run_experiment()
        assert report["avoided_count"] >= 1
        assert "Ninth Circuit citation graph" in report["memo"]


# ---------------------------------------------------------------------------
# callable via domain-mcp
# ---------------------------------------------------------------------------


class TestDomainMcpRouting:
    def test_usage_layer_routes_through_domain_mcp(self, monkeypatch):
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
                "trace_id": "00000000-0000-0000-0000-000000000075",
                "content_type": "domain",
                "parameters": {
                    "tool": "legal.build_usage_layer",
                    "arguments": {
                        "authorities": [
                            {
                                "citation": "410 U.S. 113",
                                "brief_citations": 0,
                                "opinion_citations": 4,
                            }
                        ]
                    },
                },
            },
            headers={"X-Saimon-API-Key": "sk-test-domain-key"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["avoided_count"] == 1
