"""Offline metric scoring for the eval harness."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text) -> set[str]:
    """Lowercase word-level tokenization; tolerates lists/tuples/non-str."""
    if isinstance(text, (list, tuple)):
        text = " ".join(str(item) for item in text)
    elif not isinstance(text, str):
        text = str(text)
    return set(_TOKEN_RE.findall(text.lower()))


def jaccard(a: str, b: str) -> float:
    """Token Jaccard similarity between two texts."""
    ta, tb = tokenize(a), tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def score_quality(candidate: str, expected: str) -> float:
    """Quality score in [0, 1] comparing a candidate to its golden output."""
    if not str(expected).strip() and not str(candidate).strip():
        return 1.0
    return round(jaccard(candidate, expected), 4)


def is_success(candidate: str, expected: str, threshold: float = 0.0) -> bool:
    """Binary task success: candidate is non-empty and meets the threshold."""
    if not str(candidate).strip():
        return False
    if str(expected).strip() and str(candidate).strip():
        return score_quality(candidate, expected) >= threshold
    return True


def estimate_cost(candidate: str, expected: str, token_usage=None) -> int:
    """Cost in tokens; uses fixture-provided usage when present."""
    if token_usage is not None:
        return int(token_usage)
    return len(tokenize(candidate)) + len(tokenize(expected))


def measure_latency(latency_ms=None) -> float:
    """Latency in milliseconds; defaults to 0.0 when not provided."""
    if latency_ms is None:
        return 0.0
    return float(latency_ms)
