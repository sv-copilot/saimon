"""Env wiring regression tests (SAIMON-LONGFORM-PACKAGING-1).

The retail ``plugins.legal`` plugin only loads in production when the
``SAIMON_DOMAIN_PLUGIN_PATHS`` environment variable reaches ``domain-mcp``.
Before this slice:

- ``docker-compose.yml`` defaulted the var to an empty string (``plugins: 0``).
- ``docker-compose.staging.yml`` never wired the var at all.
- ``docker-compose.prod.yml`` referenced ``${SAIMON_DOMAIN_PLUGIN_PATHS}`` with
  no fallback, so an unset host ``.env`` produced ``plugins: 0``.

These tests pin that every environment's ``domain-mcp`` declares a non-empty
fallback (``plugins.legal``) and that ``.env.example`` documents the variable.
They are source-level and do **not** require docker, so they run in the CI
``validate`` job.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Compose-specific ``!override`` tag (used by staging/prod overrides).  PyYAML's
# safe loader does not know it, so register a constructor that returns the
# tagged node's value as-is.
def _construct_override(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


yaml.SafeLoader.add_constructor("!override", _construct_override)

COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.staging.yml",
    "docker-compose.prod.yml",
)


def _load_compose(path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / path).read_text())


def _domain_environment(path: str) -> dict:
    services = _load_compose(path).get("services", {})
    domain = services.get("domain-mcp", {})
    return domain.get("environment") or {}


class TestDomainPluginEnvDocumented:
    def test_env_example_documents_plugin_paths(self):
        content = (REPO_ROOT / ".env.example").read_text()
        assert "SAIMON_DOMAIN_PLUGIN_PATHS" in content
        assert "plugins.legal" in content

    def test_env_example_documents_domain_api_key(self):
        content = (REPO_ROOT / ".env.example").read_text()
        assert "SAIMON_DOMAIN_API_KEY" in content


class TestDomainPluginEnvWired:
    @pytest.mark.parametrize("path", COMPOSE_FILES)
    def test_domain_mcp_declares_plugin_paths(self, path):
        env = _domain_environment(path)
        raw = env.get("SAIMON_DOMAIN_PLUGIN_PATHS")
        assert raw, f"{path}: domain-mcp missing SAIMON_DOMAIN_PLUGIN_PATHS"

    @pytest.mark.parametrize("path", COMPOSE_FILES)
    def test_domain_mcp_plugin_paths_has_legal_fallback(self, path):
        env = _domain_environment(path)
        raw = env.get("SAIMON_DOMAIN_PLUGIN_PATHS")
        assert raw and "plugins.legal" in raw, (
            f"{path}: domain-mcp plugin paths must fall back to plugins.legal, "
            f"got: {raw!r}"
        )
