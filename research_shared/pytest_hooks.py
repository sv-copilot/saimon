"""pytest_hooks.py — shared pytest hook helpers.

Kept importable so hook logic is unit-testable without importing a bare
``conftest.py`` (whose module name collides across the repo, since pytest
inserts multiple conftest directories onto ``sys.path``).
"""

from __future__ import annotations

import os
from typing import Any

import pytest


def skip_integration_tests_in_ci(items: list[Any]) -> None:
    """Skip ``integration``-marked tests when running in CI.

    Implements the ``integration`` marker contract declared in
    ``pyproject.toml``: tests marked ``integration`` make real network calls
    and are skipped on CI runners, where outbound access to third-party
    services (e.g. archive.org) is unavailable or unreliable.
    """
    if not os.environ.get("CI"):
        return
    skip = pytest.mark.skip(reason="integration test skipped in CI")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip)
