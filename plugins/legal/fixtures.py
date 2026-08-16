"""fixtures.py — recorded citator entries for reconciliation classification.

The reconciliation engine is pure logic: it never performs network I/O.  These
recorded citator entries (Shepard's, KeyCite, BCite, CourtListener) and brief
usage windows exercise every classification state without live credentials.
"""

from __future__ import annotations

from typing import Any

# --- classification-state fixtures -----------------------------------------

STRONG_GREEN: dict[str, Any] = {
    "citators": {
        "shepards": "followed",
        "keycite": "followed",
        "bcite": "followed",
        "courtlistener": "cited",
    },
    "usage": {"3m": 12, "6m": 25, "12m": 48, "24m": 90},
}

WEAK_GREEN: dict[str, Any] = {
    "citators": {
        "shepards": "followed",
        "keycite": "positive",
        "bcite": "cited",
    },
    "usage": {"3m": 0, "6m": 4, "12m": 10, "24m": 22},
}

YELLOW: dict[str, Any] = {
    "citators": {
        "shepards": "followed",
        "keycite": "overruled",
        "bcite": "questioned",
    },
    "usage": {"3m": 3, "6m": 6, "12m": 12, "24m": 20},
}

CITATOR_RED: dict[str, Any] = {
    "citators": {
        "shepards": "overruled",
        "keycite": "red",
        "bcite": "abrogated",
    },
    "usage": {"3m": 0, "6m": 0, "12m": 1, "24m": 3},
}

MARKET_RED: dict[str, Any] = {
    "citators": {
        "shepards": "followed",
        "keycite": "positive",
    },
    "usage": {"3m": 0, "6m": 0, "12m": 0, "24m": 0},
}

RESURRECTION: dict[str, Any] = {
    "citators": {
        "shepards": "overruled",
        "keycite": "red",
        "bcite": "negative",
    },
    "usage": {"3m": 5, "6m": 11, "12m": 20, "24m": 35},
}

#: All six classification states, keyed by canonical state name.
CLASSIFICATION_FIXTURES: dict[str, dict[str, Any]] = {
    "STRONG_GREEN": STRONG_GREEN,
    "WEAK_GREEN": WEAK_GREEN,
    "YELLOW": YELLOW,
    "CITATOR_RED": CITATOR_RED,
    "MARKET_RED": MARKET_RED,
    "RESURRECTION": RESURRECTION,
}
