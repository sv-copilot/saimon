"""Pytest root hooks.

Implements the ``integration`` marker contract declared in ``pyproject.toml``:
tests marked ``integration`` make real network calls and are skipped when
running in CI, where outbound access to third-party services (e.g. archive.org)
is unavailable or unreliable.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip ``integration``-marked tests when running in CI."""
    if os.environ.get("CI"):
        skip = pytest.mark.skip(reason="integration test skipped in CI")
        for item in items:
            if item.get_closest_marker("integration") is not None:
                item.add_marker(skip)
