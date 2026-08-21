"""Tests for research_shared.text_quality (SAIMON-OCR-QUALITY-GATE-1, #196).

The scorer must reject corrupted OCR (character-class health) while passing
clean prose — including clean non-English text (language identity is not the
signal).
"""

from __future__ import annotations

from research_shared.text_quality import (
    DEFAULT_MIN_QUALITY,
    text_quality_ok,
    text_quality_score,
)


def _clean_en() -> str:
    return ("The quick brown fox jumps over the lazy dog. ") * 40


def _clean_de() -> str:
    return (
        "David Copperfield war ein Roman von Charles Dickens. "
        "Die deutsche Übersetzung ist weit verbreitet und gut lesbar. "
        "Erzählt wird die Geschichte eines Waisenjungen, der sich durchschlägt. "
    ) * 6


def _garbled_ocr() -> str:
    # Replacement chars + block chars + control chars — heavy corruption.
    return ("\ufffd\u2588\u2588\u2593\x00\x01") * 200


class TestTextQualityScore:
    def test_clean_english_scores_high(self) -> None:
        score = text_quality_score(_clean_en())
        assert score >= DEFAULT_MIN_QUALITY
        assert score >= 0.7

    def test_clean_german_scores_high(self) -> None:
        # Umlauts are alphabetic; language identity is not penalized.
        score = text_quality_score(_clean_de())
        assert score >= DEFAULT_MIN_QUALITY

    def test_garbled_ocr_scores_low(self) -> None:
        score = text_quality_score(_garbled_ocr())
        assert score < DEFAULT_MIN_QUALITY

    def test_short_text_scores_zero(self) -> None:
        assert text_quality_score("") == 0.0
        assert text_quality_score("too short") == 0.0

    def test_score_bounds(self) -> None:
        assert 0.0 <= text_quality_score(_clean_en()) <= 1.0
        assert 0.0 <= text_quality_score(_garbled_ocr()) <= 1.0


class TestTextQualityOk:
    def test_clean_passes_default_threshold(self, monkeypatch) -> None:
        monkeypatch.delenv("FULLTEXT_MIN_QUALITY", raising=False)
        assert text_quality_ok(_clean_en()) is True

    def test_garbled_fails_default_threshold(self, monkeypatch) -> None:
        monkeypatch.delenv("FULLTEXT_MIN_QUALITY", raising=False)
        assert text_quality_ok(_garbled_ocr()) is False

    def test_zero_threshold_disables_gate(self) -> None:
        assert text_quality_ok(_garbled_ocr(), threshold=0.0) is True

    def test_env_knob_off_disables_gate(self, monkeypatch) -> None:
        monkeypatch.setenv("FULLTEXT_MIN_QUALITY", "off")
        assert text_quality_ok(_garbled_ocr()) is True
