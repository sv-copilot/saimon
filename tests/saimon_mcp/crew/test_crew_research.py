"""Tests for crew.research@v1.

The tool previously depended on CrewAI being importable and on an agent having
tools it was never given. It returned "crewai import failed" in production while
the service reported healthy, and these tests were skipped whenever crewai was
absent — which is why nobody noticed. They now exercise the direct path that
actually runs.
"""

from __future__ import annotations

import asyncio

import pytest

from saimon_mcp.crew import research


def passage(title: str, body: str) -> dict:
    return {"id": title[:8], "title": title, "body": body}


class _FakeClient:
    def __init__(self, reply: str, *, raises: bool = False) -> None:
        self.reply = reply
        self.raises = raises
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.raises:
            raise RuntimeError("upstream 502")
        return self.reply


def patch_llm(monkeypatch: pytest.MonkeyPatch, reply: str, *, raises: bool = False):
    client = _FakeClient(reply, raises=raises)

    class _Config:
        api_key = "test-key"

        @classmethod
        def from_env(cls):
            return cls()

    class _Client:
        def __init__(self, config):
            self._config = config

        async def generate(self, prompt):
            return await client.generate(prompt)

    monkeypatch.setattr("research_shared.llm.LLMConfig", _Config, raising=False)
    monkeypatch.setattr("research_shared.llm.LLMClient", _Client, raising=False)
    return client


class TestRetrieval:
    def test_no_api_key_means_no_passages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAIMON_API_KEY", raising=False)
        assert research.search_passages("anything") == []

    def test_context_numbers_the_passages(self) -> None:
        context = research.format_context([
            passage("Slice lifecycle", "Eleven states."),
            passage("Seam", "The PMO names slices."),
        ])
        assert context.startswith("[1] Slice lifecycle: Eleven states.")
        assert "[2] Seam:" in context


class TestRunResearch:
    def test_no_passages_reports_unavailable_not_invention(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(research, "search_passages", lambda topic, limit=8: [])
        result = asyncio.run(research.run_research("a topic the corpus lacks"
                                                   ""))
        assert result["confirmed"] == []
        assert "no passages retrieved" in result["unavailable"][0]

    def test_answer_is_grounded_in_the_retrieved_passages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            research,
            "search_passages",
            lambda topic, limit=8: [passage("Slice lifecycle", "A slice has eleven states.")],
        )
        client = patch_llm(
            monkeypatch,
            '{"confirmed": ["A slice has eleven states."], "inferred": [], "unavailable": []}',
        )
        result = asyncio.run(research.run_research("How many lifecycle states?"))
        assert result["confirmed"] == ["A slice has eleven states."]
        assert result["citations"][0]["title"] == "Slice lifecycle"
        assert "A slice has eleven states." in client.prompts[0]

    def test_a_failed_call_reports_the_cause_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            research, "search_passages", lambda topic, limit=8: [passage("T", "B")]
        )
        patch_llm(monkeypatch, "", raises=True)
        result = asyncio.run(research.run_research("topic"))
        assert result["confirmed"] == []
        assert "RuntimeError" in result["unavailable"][0]

    def test_malformed_output_is_not_salvaged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            research, "search_passages", lambda topic, limit=8: [passage("T", "B")]
        )
        patch_llm(monkeypatch, "I think the answer is probably eleven.")
        result = asyncio.run(research.run_research("topic"))
        assert result["confirmed"] == []
        assert result["unavailable"] == ["could not parse crew output"]

    def test_json_wrapped_in_prose_is_parsed(self) -> None:
        parsed = research.parse_answer(
            'Here you go:\n{"confirmed": ["a"], "inferred": [], "unavailable": ["b"]}\nDone.'
        )
        assert parsed == {"confirmed": ["a"], "inferred": [], "unavailable": ["b"]}
