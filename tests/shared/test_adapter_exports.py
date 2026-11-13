"""Smoke test for the adapter public surface (#79 SAIMON-SMOKE-SLICE-1).

Proves the saimon slice pipeline end-to-end: every adapter is importable
and exported from the package's public namespace.
"""

from __future__ import annotations

import importlib

EXPECTED_ADAPTERS = [
    "InternetArchiveAdapter",
]


def test_all_adapters_exported_from_package() -> None:
    """research_shared.adapters exports all five shadow-library adapters."""
    import research_shared.adapters as adapters

    public = set(adapters.__all__)
    for name in EXPECTED_ADAPTERS:
        assert name in public, f"{name} missing from adapters.__all__"


def test_all_adapters_importable() -> None:
    """Each adapter module exposes its adapter class."""
    modules = {
        "InternetArchiveAdapter": "research_shared.adapters.internet_archive",
    }
    for name, module_path in modules.items():
        module = importlib.import_module(module_path)
        assert hasattr(module, name), f"{module_path} missing {name}"
