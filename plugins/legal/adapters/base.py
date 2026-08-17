"""base.py — shared helpers for legal source adapters."""

from __future__ import annotations

from typing import Any


def parse_year(value: Any) -> int | None:
    """Extract a publication/decision year from a date-ish value."""
    if value is None:
        return None
    text = str(value)[:4]
    return int(text) if text.isdigit() else None
