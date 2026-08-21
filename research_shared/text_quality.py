"""text_quality.py — fail-closed minimum text-quality gate for downloaded full text.

SAIMON-OCR-QUALITY-GATE-1 (#196): garbled OCR (e.g. the David Copperfield
German OCR) was ingested and polluted the vector index. This module scores
extracted text on *character-class health* — alphabetic ratio, garbage /
replacement ratio, and single-character repetition — so corrupted text is
rejected without discriminating on language identity.

All scoring is pure and deterministic; no network, no model.
"""

from __future__ import annotations

import os
import re

DEFAULT_MIN_QUALITY = 0.5
MIN_TEXT_LENGTH = 100

_WHITESPACE = re.compile(r"\s+")

# Environment knob. Default ON (0.5). Set to "off"/"0"/"false" to disable.
_FULLTEXT_MIN_QUALITY_ENV = "FULLTEXT_MIN_QUALITY"


def _is_garbage(char: str) -> bool:
    """True for replacement/control characters that signal corrupt text."""
    if char == "\ufffd":  # Unicode replacement character
        return True
    code = ord(char)
    return code < 32 and char not in (" ", "\n", "\t", "\r")


def _longest_run_ratio(text: str) -> float:
    """Fraction of *text* inside its longest run of a single repeated char."""
    if not text:
        return 0.0
    longest = 1
    run = 1
    for index in range(1, len(text)):
        if text[index] == text[index - 1]:
            run += 1
        else:
            longest = max(longest, run)
            run = 1
    longest = max(longest, run)
    return longest / len(text)


def text_quality_score(text: str) -> float:
    """Score extracted text quality in [0, 1] (higher is healthier).

    Too-short text scores 0. Otherwise the score combines alphabetic ratio,
    (1 - garbage ratio), and (1 - longest-repetition ratio).
    """
    normalized = _WHITESPACE.sub(" ", text or "").strip()
    if len(normalized) < MIN_TEXT_LENGTH:
        return 0.0

    total = len(normalized)
    letters = sum(1 for char in normalized if char.isalpha())
    garbage = sum(1 for char in normalized if _is_garbage(char))

    letter_ratio = letters / total
    garbage_ratio = garbage / total
    repetition_ratio = _longest_run_ratio(normalized)

    score = letter_ratio * (1.0 - garbage_ratio) * (1.0 - repetition_ratio)
    return max(0.0, min(1.0, score))


def _env_threshold() -> float:
    raw = os.environ.get(_FULLTEXT_MIN_QUALITY_ENV, "").strip().lower()
    if not raw:
        return DEFAULT_MIN_QUALITY
    if raw in ("off", "false", "no", "0"):
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_MIN_QUALITY


def text_quality_ok(text: str, threshold: float | None = None) -> bool:
    """Return True when *text* passes the minimum quality gate.

    A threshold of 0 disables the gate (always passes). When *threshold* is
    None, the ``FULLTEXT_MIN_QUALITY`` env knob (default 0.5) is used.
    """
    if threshold is None:
        threshold = _env_threshold()
    if threshold <= 0:
        return True
    return text_quality_score(text) >= threshold
