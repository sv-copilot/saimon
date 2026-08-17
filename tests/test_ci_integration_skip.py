"""Tests for the CI integration-test skip hook (slice #80).

``pyproject.toml`` declares the ``integration`` marker as "marks tests that
make real network calls (skipped in CI)".  The root ``conftest.py`` implements
that skip, and the shadow-search integration tests (which hit archive.org
live) are marked ``integration``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from research_shared.pytest_hooks import skip_integration_tests_in_ci


class FakeItem:
    """Minimal stand-in for a pytest Item exercising the skip hook."""

    def __init__(self, marker_names: tuple[str, ...]) -> None:
        self._marker_names = list(marker_names)
        self.own_markers: list[Any] = []

    def get_closest_marker(self, name: str) -> str | None:
        return name if name in self._marker_names else None

    def add_marker(self, marker: Any) -> None:
        self.own_markers.append(marker)


class TestCiIntegrationSkipHook:
    def test_skips_integration_marked_tests_in_ci(self, monkeypatch):
        monkeypatch.setenv("CI", "true")
        plain = FakeItem(())
        integration = FakeItem(("integration",))
        skip_integration_tests_in_ci([plain, integration])
        assert plain.own_markers == []
        assert [marker.name for marker in integration.own_markers] == ["skip"]

    def test_does_not_skip_unmarked_tests_in_ci(self, monkeypatch):
        monkeypatch.setenv("CI", "true")
        plain = FakeItem(())
        skip_integration_tests_in_ci([plain])
        assert plain.own_markers == []

    def test_does_not_skip_outside_ci(self, monkeypatch):
        monkeypatch.delenv("CI", raising=False)
        integration = FakeItem(("integration",))
        skip_integration_tests_in_ci([integration])
        assert integration.own_markers == []


class TestShadowSearchMarkedIntegration:
    def test_shadow_search_module_is_marked_integration(self):
        path = Path("tests/mcp/test_integration/test_shadow_search_integration.py")
        spec = importlib.util.spec_from_file_location("shadow_search_integration", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        marker = getattr(module, "pytestmark", None)
        assert marker is not None
        assert marker.name == "integration"
