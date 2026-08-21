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


def _clean_fr() -> str:
    return (
        "Le renard brun saute par-dessus le chien paresseux. "
        "L'école est ouverte aujourd'hui et les enfants lisent un livre. "
        "La traduction française est largement répandue et bien lisible. "
    ) * 6


def _clean_es() -> str:
    return (
        "El rápido zorro marrón salta sobre el perro perezoso. "
        "¿Cómo estás hoy? ¡Qué bonito es el campo en verano! "
        "La traducción española está muy extendida y se lee bien. "
    ) * 6


def _copperfield_ocr() -> str:
    """OCR-substituted German Copperfield sample.

    This is the 2026-08-21 sample that the #196 character-class gate scored
    0.69-0.74 (passes >=0.5) because its corruption is lookalike substitution
    rather than garbage glyphs: ``b``/``d`` → ``©``, ``Sch`` → ``5``,
    ``st`` → ``5t``, ``ei`` → ``3i``. The strengthened scorer (#200) must
    reject it via OCR-substitution signals.
    """
    clean = (
        "David Copperfield war ein Roman von Charles Dickens. "
        "Die deutsche Übersetzung erzählt die Geschichte eines Waisenjungen, "
        "der sich durch das harte Leben in London schlägt. "
        "Der Junge arbeitet in einer Fabrik und lernt, was Armut bedeutet. "
        "Später wird er ein erfolgreicher Schriftsteller und findet sein Glück. "
    ) * 8
    return (
        clean.replace("b", "©")
        .replace("d", "©")
        .replace("Sch", "5")
        .replace("sch", "5")
        .replace("st", "5t")
        .replace("ei", "3i")
    )


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


class TestOcrSubstitutionStrength:
    """SAIMON-QUALITY-SCORER-STRENGTHEN-1 (#200): OCR-substituted text fails."""

    def test_copperfield_ocr_scores_below_threshold(self) -> None:
        # Before the fix this scored 0.69-0.74 (passes). It must now fail.
        score = text_quality_score(_copperfield_ocr())
        assert score < DEFAULT_MIN_QUALITY

    def test_clean_french_scores_high(self) -> None:
        score = text_quality_score(_clean_fr())
        assert score >= DEFAULT_MIN_QUALITY

    def test_clean_spanish_scores_high(self) -> None:
        score = text_quality_score(_clean_es())
        assert score >= DEFAULT_MIN_QUALITY

    def test_copperfield_ocr_fails_default_gate(self, monkeypatch) -> None:
        monkeypatch.delenv("FULLTEXT_MIN_QUALITY", raising=False)
        assert text_quality_ok(_copperfield_ocr()) is False

    def test_copperfield_ocr_passes_when_gate_disabled(self) -> None:
        assert text_quality_ok(_copperfield_ocr(), threshold=0.0) is True
