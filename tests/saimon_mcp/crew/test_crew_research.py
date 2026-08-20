"""Tests for crew.research@v1 (SAIMON-CREW-RESEARCH-1)."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

from saimon_mcp.crew.llm import CrewLLMResolution


class _FakeTask:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeAgent:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeCrew:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.fixture
def crewai_mock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    mock.__path__ = []
    mock.Agent = _FakeAgent
    mock.Task = _FakeTask
    mock.Crew = _FakeCrew
    mock.Process = MagicMock()
    monkeypatch.setitem(sys.modules, "crewai", mock)
    return mock


class TestResearchCrew:
    def test_builds_single_research_analyst_agent_with_grounding_rule(
        self, crewai_mock: MagicMock
    ) -> None:
        from saimon_mcp.crew.research import build_research_crew

        crew = build_research_crew(MagicMock(), max_messages=5)
        assert len(crew.agents) == 1
        agent = crew.agents[0]
        assert agent.role == "Research Analyst"
        task = crew.tasks[0]
        assert "confirmed" in task.description
        assert "inferred" in task.description
        assert "unavailable" in task.description
        assert "NEVER invent" in task.description

    def test_context_bounded_to_last_n_messages(self, crewai_mock: MagicMock) -> None:
        from saimon_mcp.crew.research import build_research_crew

        crew = build_research_crew(MagicMock(), max_messages=5)
        # Bounded context: no chaining, single task, no accumulated history.
        assert crew.tasks[0].context == []
        assert "bounded to the last N messages" in crew.agents[0].backstory


class TestRunResearch:
    def test_run_research_returns_empty_when_llm_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from saimon_mcp.crew import research

        monkeypatch.setattr(
            research,
            "make_crew_llm",
            lambda route: CrewLLMResolution(None, "no DEEPSEEK_API_KEY"),
        )
        result = asyncio.run(research.run_research("some topic"))
        assert result["confirmed"] == []
        assert result["inferred"] == []
        assert result["unavailable"]  # graceful degradation, no crash

    def test_run_research_surfaces_real_llm_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#190 — the unavailable[] reason must name the true cause, not a
        blanket 'no DEEPSEEK_API_KEY' when the failure is elsewhere."""
        from saimon_mcp.crew import research

        real_cause = (
            "crewai import failed: ModuleNotFoundError: "
            "No module named 'mcp.shared'"
        )
        monkeypatch.setattr(
            research,
            "make_crew_llm",
            lambda route: CrewLLMResolution(None, real_cause),
        )
        result = asyncio.run(research.run_research("topic"))
        assert result["unavailable"] == [f"crew LLM unavailable — {real_cause}"]
        assert "no DEEPSEEK_API_KEY" not in result["unavailable"][0]

    def test_run_research_routes_to_declared_saimon_research(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#190 — crew.research@v1 must resolve the declared saimon.research
        route; never an undeclared crew.* route."""
        from saimon_mcp.crew import research

        routes: list[str] = []

        def spy(route: str) -> CrewLLMResolution:
            routes.append(route)
            return CrewLLMResolution(MagicMock())

        monkeypatch.setattr(research, "make_crew_llm", spy)
        monkeypatch.setattr(
            research, "build_research_crew", lambda llm, max_messages=10: MagicMock()
        )
        asyncio.run(research.run_research("topic"))
        assert routes == ["saimon.research"]

    def test_run_research_no_invention_on_malformed_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from saimon_mcp.crew import research

        fake_llm = MagicMock()
        fake_crew = MagicMock()
        fake_crew.kickoff.return_value = MagicMock(raw="not json at all")
        monkeypatch.setattr(
            research, "make_crew_llm", lambda route: CrewLLMResolution(fake_llm)
        )
        monkeypatch.setattr(research, "build_research_crew", lambda llm, max_messages=10: fake_crew)

        result = asyncio.run(research.run_research("topic"))
        assert result["confirmed"] == []
        assert result["unavailable"] == ["could not parse crew output"]

    def test_run_research_parses_grounded_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from saimon_mcp.crew import research

        fake_crew = MagicMock()
        fake_crew.kickoff.return_value = MagicMock(
            raw='{"confirmed": ["fact"], "inferred": ["guess"], "unavailable": []}'
        )
        monkeypatch.setattr(
            research,
            "make_crew_llm",
            lambda route: CrewLLMResolution(MagicMock()),
        )
        monkeypatch.setattr(research, "build_research_crew", lambda llm, max_messages=10: fake_crew)

        result = asyncio.run(research.run_research("topic"))
        assert result["confirmed"] == ["fact"]
        assert result["inferred"] == ["guess"]
        assert result["unavailable"] == []
