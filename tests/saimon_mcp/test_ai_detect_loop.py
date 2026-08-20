"""Tests for SAIMON-AI-DETECT-LOOP (#39) — auto-iterate until AI
detection passes using the evaluate service's 12-check heuristic.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evaluate_response(score: float, flags: list[str] | None = None) -> dict:
    """Build a mock evaluate_content response for a given AI detection score."""
    if flags is None:
        justification = (
            f"AI detection: {score:.2f}. Deterministic heuristic — not an ML classifier. "
            "No strong AI fingerprints detected in 100 words across 8 sentences."
        )
    else:
        justification = (
            f"AI detection: {score:.2f}. Deterministic heuristic — not an ML classifier. "
            f"Flags: {'; '.join(flags)}. (100 words, 8 sentences)"
        )
    return {
        "data": {
            "scores": [
                {
                    "criterion": "ai_detection",
                    "score": score,
                    "max_score": 1.0,
                    "justification": justification,
                }
            ],
            "overall_score": score,
            "criteria_count": 1,
        }
    }


# ---------------------------------------------------------------------------
# Test 5: _parse_failing_flags
# ---------------------------------------------------------------------------

class TestParseFailingFlags:
    """Unit tests for _parse_failing_flags — extracts flag names from
    the evaluate service justification string."""

    def test_single_flag(self):
        """Single flag is extracted correctly."""
        from saimon_mcp.generate.server import _parse_failing_flags  # type: ignore[attr-defined]

        justification = (
            "AI detection: 0.35. Deterministic heuristic — not an ML classifier. "
            "Flags: 3 template phrases (0.35). (100 words, 8 sentences)"
        )
        flags = _parse_failing_flags(justification)
        assert flags == ["template phrases"]

    def test_multiple_flags(self):
        """Multiple flags are extracted correctly."""
        from saimon_mcp.generate.server import _parse_failing_flags  # type: ignore[attr-defined]

        justification = (
            "AI detection: 0.35. Deterministic heuristic — not an ML classifier. "
            "Flags: 3 template phrases (0.12); no personal stance (0.45); "
            "uniform sentences (0.42). (200 words, 15 sentences)"
        )
        flags = _parse_failing_flags(justification)
        assert flags == ["template phrases", "no personal stance", "uniform sentences"]

    def test_no_flags(self):
        """When no flags are present, returns empty list."""
        from saimon_mcp.generate.server import _parse_failing_flags  # type: ignore[attr-defined]

        justification = (
            "AI detection: 0.85. Deterministic heuristic — not an ML classifier. "
            "No strong AI fingerprints detected in 100 words across 8 sentences."
        )
        flags = _parse_failing_flags(justification)
        assert flags == []

    def test_empty_justification(self):
        """Empty justification returns empty list."""
        from saimon_mcp.generate.server import _parse_failing_flags  # type: ignore[attr-defined]

        assert _parse_failing_flags("") == []
        assert _parse_failing_flags(None) == []  # type: ignore[arg-type]

    def test_justification_with_score_numbers_but_no_flags(self):
        """Justification with score numbers but no 'Flags:' section."""
        from saimon_mcp.generate.server import _parse_failing_flags  # type: ignore[attr-defined]

        justification = (
            "AI detection: 0.85. Deterministic heuristic — not an ML classifier. "
            "No strong AI fingerprints detected in 100 words across 8 sentences."
        )
        flags = _parse_failing_flags(justification)
        assert flags == []


# ---------------------------------------------------------------------------
# Test 6: _build_anti_pattern_prompt
# ---------------------------------------------------------------------------

class TestBuildAntiPatternPrompt:
    """Unit tests for _build_anti_pattern_prompt — maps flag names to
    specific writing guidance."""

    def test_all_flags_mapped(self):
        """All 12 flag types produce guidance strings."""
        from saimon_mcp.generate.server import _build_anti_pattern_prompt  # type: ignore[attr-defined]

        all_flags = [
            "template phrases", "corporate neutrality", "low burstiness",
            "uniform sentences", "low lexical diversity", "no personal stance",
            "formulaic transitions", "bullet-point addiction", "over-hedging",
            "inflated adjectives", "narrow punctuation", "low starter diversity",
        ]
        result = _build_anti_pattern_prompt(all_flags)
        assert len(result) > 0
        assert "template phrases" in result.lower() or "Avoid formulaic" in result
        assert "corporate neutrality" in result.lower() or "Take a clear stance" in result

    def test_single_flag_gives_targeted_guidance(self):
        """Single flag produces specific guidance for that flag."""
        from saimon_mcp.generate.server import _build_anti_pattern_prompt  # type: ignore[attr-defined]

        result = _build_anti_pattern_prompt(["over-hedging"])
        assert len(result) > 0
        assert "hedging" in result.lower()

    def test_empty_flags_returns_empty_string(self):
        """Empty flag list returns empty string."""
        from saimon_mcp.generate.server import _build_anti_pattern_prompt  # type: ignore[attr-defined]

        assert _build_anti_pattern_prompt([]) == ""

    def test_unknown_flag_does_not_crash(self):
        """Unknown flag name is ignored gracefully."""
        from saimon_mcp.generate.server import _build_anti_pattern_prompt  # type: ignore[attr-defined]

        result = _build_anti_pattern_prompt(["some-random-flag"])
        assert result == ""


# ---------------------------------------------------------------------------
# Test 1-4, 7: _iterate_until_human_like
# ---------------------------------------------------------------------------

class TestIterateUntilHumanLike:
    """Integration-level tests for _iterate_until_human_like."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch):
        """Ensure consistent env for all tests."""
        monkeypatch.setenv("SAIMON_API_KEY", "sk-test-generate-key")
        monkeypatch.setenv("EVALUATE_MCP_URL", "http://fake-evaluate:8004")

    # ── Test 1: Score 0.3 → regeneration triggered ──

    @pytest.mark.asyncio
    async def test_low_score_triggers_regeneration(self, monkeypatch):
        """When evaluate returns 0.3, regeneration is triggered."""
        from saimon_mcp.generate.server import _iterate_until_human_like  # type: ignore[attr-defined]

        monkeypatch.setenv("SAIMON_AI_DETECT_MAX_RETRIES", "2")
        monkeypatch.setenv("SAIMON_AI_DETECT_THRESHOLD", "0.5")

        # Mock the evaluate HTTP call: first call 0.3, second 0.6 (pass)
        call_count = [0]
        async def mock_evaluate(content):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_evaluate_response(
                    0.3, ["3 template phrases (0.35)", "no personal stance (0.45)"]
                )
            else:
                return _make_evaluate_response(
                    0.6, []
                )

        # Mock _generate_via_llm to return "regenerated" content
        async def mock_generate(prompt, ct, tone, ct_schema, sources=None, skip_critique=True):
            return "This is regenerated content with more personality."

        with patch(
            "saimon_mcp.generate.server._call_evaluate", side_effect=mock_evaluate
        ), patch(
            "saimon_mcp.generate.server._generate_via_llm", side_effect=mock_generate
        ):
            content, iteration_log = await _iterate_until_human_like(
                original_prompt="Write about AI",
                content="Original AI-sounding content.",
                content_type="blog_post",
                tone="analytical",
                ct_schema=None,
                sources=None,
            )

        assert call_count[0] == 2  # called twice (0.3 fail, 0.6 pass)
        assert len(iteration_log) == 2
        assert iteration_log[0]["score"] == 0.3
        assert iteration_log[1]["score"] == 0.6
        assert "regenerated" in content

    # ── Test 2: Score 0.6 → loop stops immediately ──

    @pytest.mark.asyncio
    async def test_high_score_stops_immediately(self, monkeypatch):
        """When evaluate returns 0.6, loop stops immediately (PASS)."""
        from saimon_mcp.generate.server import _iterate_until_human_like  # type: ignore[attr-defined]

        monkeypatch.setenv("SAIMON_AI_DETECT_MAX_RETRIES", "3")
        monkeypatch.setenv("SAIMON_AI_DETECT_THRESHOLD", "0.5")

        async def mock_evaluate(content):
            return _make_evaluate_response(0.6, [])

        with patch(
            "saimon_mcp.generate.server._call_evaluate", side_effect=mock_evaluate
        ):
            content, iteration_log = await _iterate_until_human_like(
                original_prompt="Write about AI",
                content="Good human-sounding content.",
                content_type="blog_post",
                tone="analytical",
                ct_schema=None,
                sources=None,
            )

        assert len(iteration_log) == 1
        assert iteration_log[0]["score"] == 0.6
        assert content == "Good human-sounding content."

    # ── Test 3: Score 0.3, 0.4, 0.3 → best (0.4) returned after 3 retries ──

    @pytest.mark.asyncio
    async def test_all_fail_returns_best(self, monkeypatch):
        """After 3 retries all failing, best score content is returned."""
        from saimon_mcp.generate.server import _iterate_until_human_like  # type: ignore[attr-defined]

        monkeypatch.setenv("SAIMON_AI_DETECT_MAX_RETRIES", "3")
        monkeypatch.setenv("SAIMON_AI_DETECT_THRESHOLD", "0.5")

        scores = [0.3, 0.4, 0.3, 0.3]  # initial + 3 retries
        score_idx = [0]

        async def mock_evaluate(content):
            s = scores[score_idx[0]]
            score_idx[0] += 1
            return _make_evaluate_response(s, ["template phrases (0.35)"])

        async def mock_generate(prompt, ct, tone, ct_schema, sources=None, skip_critique=True):
            return f"Regenerated content v{score_idx[0]}"

        with patch(
            "saimon_mcp.generate.server._call_evaluate", side_effect=mock_evaluate
        ), patch(
            "saimon_mcp.generate.server._generate_via_llm", side_effect=mock_generate
        ):
            content, iteration_log = await _iterate_until_human_like(
                original_prompt="Write about AI",
                content="Original content.",
                content_type="blog_post",
                tone="analytical",
                ct_schema=None,
                sources=None,
            )

        # 4 evaluate calls: initial + 3 retries
        assert score_idx[0] == 4
        # Best score was 0.4, which is in iteration_log[1]
        best_scores = [e["score"] for e in iteration_log]
        assert max(best_scores) == 0.4
        # Content should be v2 (from score 0.4 regeneration)
        assert "Regenerated content" in content

    # ── Test 4: MAX_RETRIES=0 → no loop (backward compatible) ──

    @pytest.mark.asyncio
    async def test_zero_retries_no_loop(self, monkeypatch):
        """SAIMON_AI_DETECT_MAX_RETRIES=0 disables the loop entirely."""
        from saimon_mcp.generate.server import _iterate_until_human_like  # type: ignore[attr-defined]

        monkeypatch.setenv("SAIMON_AI_DETECT_MAX_RETRIES", "0")

        async def mock_evaluate(content):
            return _make_evaluate_response(0.3, ["template phrases (0.35)"])

        with patch(
            "saimon_mcp.generate.server._call_evaluate", side_effect=mock_evaluate
        ):
            content, iteration_log = await _iterate_until_human_like(
                original_prompt="Write about AI",
                content="Original content.",
                content_type="blog_post",
                tone="analytical",
                ct_schema=None,
                sources=None,
            )

        # No evaluate calls made at all
        assert len(iteration_log) == 0
        assert content == "Original content."

    # ── Test 7: Evaluate service unavailable → neutral fallback ──

    @pytest.mark.asyncio
    async def test_evaluate_unavailable_neutral_fallback(self, monkeypatch):
        """When evaluate service is down, neutral fallback score 0.5 is used."""
        from saimon_mcp.generate.server import _iterate_until_human_like  # type: ignore[attr-defined]

        monkeypatch.setenv("SAIMON_AI_DETECT_MAX_RETRIES", "3")
        monkeypatch.setenv("SAIMON_AI_DETECT_THRESHOLD", "0.5")

        async def mock_evaluate_error(content):
            raise Exception("Connection refused")

        with patch(
            "saimon_mcp.generate.server._call_evaluate", side_effect=mock_evaluate_error
        ):
            content, iteration_log = await _iterate_until_human_like(
                original_prompt="Write about AI",
                content="Original content.",
                content_type="blog_post",
                tone="analytical",
                ct_schema=None,
                sources=None,
            )

        # Falls back to neutral score 0.5 ≥ threshold → PASS
        assert len(iteration_log) == 1
        assert iteration_log[0]["score"] == 0.5
        assert content == "Original content."


# ---------------------------------------------------------------------------
# Test: _call_evaluate — basic HTTP call
# ---------------------------------------------------------------------------

class TestCallEvaluate:
    """Unit tests for _call_evaluate — inter-service HTTP call."""

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Successful evaluate call returns parsed response data."""
        from saimon_mcp.generate.server import _call_evaluate  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_evaluate_response(0.6, [])

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await _call_evaluate("Test content")
            assert result["data"]["scores"][0]["score"] == 0.6

    @pytest.mark.asyncio
    async def test_error_returns_neutral_fallback(self):
        """HTTP error returns neutral fallback."""
        from saimon_mcp.generate.server import _call_evaluate  # type: ignore[attr-defined]

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = Exception("Network error")

            result = await _call_evaluate("Test content")
            assert result["data"]["scores"][0]["score"] == 0.5
