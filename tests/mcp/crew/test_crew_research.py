"""Tests for crew.research@v1 (SAIMON-CREW-RESEARCH-1)."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest


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
        from mcp.crew.research import build_research_crew

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
        from mcp.crew.research import build_research_crew

        crew = build_research_crew(MagicMock(), max_messages=5)
        # Bounded context: no chaining, single task, no accumulated history.
        assert crew.tasks[0].context == []
        assert "bounded to the last N messages" in crew.agents[0].backstory


class TestRunResearch:
    def test_run_research_returns_empty_when_llm_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp.crew import research

        monkeypatch.setattr(research, "make_crew_llm", lambda route: None)
        result = asyncio.run(research.run_research("some topic"))
        assert result["confirmed"] == []
        assert result["inferred"] == []
        assert result["unavailable"]  # graceful degradation, no crash

    def test_run_research_no_invention_on_malformed_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp.crew import research

        fake_llm = MagicMock()
        fake_crew = MagicMock()
        fake_crew.kickoff.return_value = MagicMock(raw="not json at all")
        monkeypatch.setattr(research, "make_crew_llm", lambda route: fake_llm)
        monkeypatch.setattr(research, "build_research_crew", lambda llm, max_messages=10: fake_crew)

        result = asyncio.run(research.run_research("topic"))
        assert result["confirmed"] == []
        assert result["unavailable"] == ["could not parse crew output"]

    def test_run_research_parses_grounded_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp.crew import research

        fake_crew = MagicMock()
        fake_crew.kickoff.return_value = MagicMock(
            raw='{"confirmed": ["fact"], "inferred": ["guess"], "unavailable": []}'
        )
        monkeypatch.setattr(research, "make_crew_llm", lambda route: MagicMock())
        monkeypatch.setattr(research, "build_research_crew", lambda llm, max_messages=10: fake_crew)

        result = asyncio.run(research.run_research("topic"))
        assert result["confirmed"] == ["fact"]
        assert result["inferred"] == ["guess"]
        assert result["unavailable"] == []
