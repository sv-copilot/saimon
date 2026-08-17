"""Pytest root hooks.

Hooks are thin wrappers over :mod:`research_shared.pytest_hooks` so the skip
logic stays importable and unit-testable (a bare ``conftest`` module name
collides across the repo when multiple conftest directories are on
``sys.path``).
"""

from __future__ import annotations

from research_shared.pytest_hooks import skip_integration_tests_in_ci


def pytest_collection_modifyitems(config, items):
    """Skip ``integration``-marked tests when running in CI."""
    skip_integration_tests_in_ci(items)
