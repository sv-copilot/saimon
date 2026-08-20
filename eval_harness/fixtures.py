"""Fixture suite loading for the offline eval harness."""

from __future__ import annotations

import json
from pathlib import Path


def load_fixtures(fixtures_root: str, suite_name: str) -> list[dict]:
    """Load the fixture list for a named suite.

    Reads ``<fixtures_root>/<suite_name>/fixtures.json``. Accepts either a
    bare JSON array or an object with a ``fixtures`` key.
    """
    path = Path(fixtures_root) / suite_name / "fixtures.json"
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        return data.get("fixtures", [])
    return data


def list_suites(fixtures_root: str) -> list[str]:
    """List suites (directories containing a ``fixtures.json``)."""
    root = Path(fixtures_root)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if (p / "fixtures.json").is_file()
    )
