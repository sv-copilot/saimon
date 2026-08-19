"""Compose merge tag tests (SAIMON-STAGING-DEPLOY-FIX-1).

Guards against the wrong-version leak that motivated the slice:

- ``docker-compose.staging.yml`` must override *every* MCP service to ``:rc``
  (previously it omitted ``api-mcp`` + ``domain-mcp``, so the merged config
  pulled them ``:dev`` from base).
- ``docker-compose.prod.yml`` must override ``domain-mcp`` to ``:main``
  (previously it omitted the service entirely, so prod ran ``domain-mcp:dev``).

``PyYAML`` is NOT in ``requirements.txt``, so this test does **not** reimplement
the compose merge in Python.  It shells out to the authoritative
``docker compose config --format json`` and parses the result with stdlib
``json``.  When ``docker`` is unavailable (e.g. the ubuntu ``validate`` CI job)
the whole module is skipped.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

DEV_IMAGE = "ghcr.io/sv-copilot/saimon:dev"
RC_IMAGE = "ghcr.io/sv-copilot/saimon:rc"
MAIN_IMAGE = "ghcr.io/sv-copilot/saimon:main"
POSTGRES_IMAGE = "pgvector/pgvector:pg16"

# Every MCP service defined in the base compose file.  Each one must resolve to
# the branch tag of the environment merge (never :dev).
MCP_SERVICES = (
    "search-mcp",
    "generate-mcp",
    "export-mcp",
    "evaluate-mcp",
    "verify-mcp",
    "explore-mcp",
    "api-mcp",
    "domain-mcp",
)


def _docker_compose_available() -> bool:
    return shutil.which("docker") is not None


def _merged_config(*files: str) -> dict:
    """Return the merged compose config as a dict for the given file stack."""
    args = ["docker", "compose"]
    for f in files:
        args += ["-f", str(REPO_ROOT / f)]
    args += ["config", "--format", "json"]

    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"docker compose config failed (exit {proc.returncode}):\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


def _service_images(config: dict) -> dict[str, str]:
    return {
        name: svc.get("image", "")
        for name, svc in config.get("services", {}).items()
    }


pytestmark = pytest.mark.skipif(
    not _docker_compose_available(), reason="docker compose not installed"
)


def _assert_no_dev_images(images: dict[str, str]) -> None:
    dev_services = [name for name, image in images.items() if image == DEV_IMAGE]
    assert not dev_services, f":dev leaked into merge for services: {dev_services}"


@pytest.fixture(scope="module")
def staging_config() -> dict:
    return _merged_config("docker-compose.yml", "docker-compose.staging.yml")


@pytest.fixture(scope="module")
def prod_config() -> dict:
    return _merged_config("docker-compose.yml", "docker-compose.prod.yml")


def test_staging_has_no_dev_image_leak(staging_config):
    _assert_no_dev_images(_service_images(staging_config))


def test_staging_all_mcp_services_resolve_to_rc(staging_config):
    images = _service_images(staging_config)
    wrong = {
        name: image
        for name, image in images.items()
        if name in MCP_SERVICES and image != RC_IMAGE
    }
    assert not wrong, f"staging MCP services must use :rc, got: {wrong}"


def test_staging_postgres_uses_pgvector_pg16(staging_config):
    assert _service_images(staging_config)["postgres"] == POSTGRES_IMAGE


def test_staging_domain_mcp_has_loopback_port(staging_config):
    domain = staging_config["services"]["domain-mcp"]
    loopback = [
        p for p in domain.get("ports", [])
        if p.get("host_ip") == "127.0.0.1" and p.get("published") == "8108"
    ]
    assert loopback, "domain-mcp staging override missing loopback 127.0.0.1:8108"


def test_prod_has_no_dev_image_leak(prod_config):
    _assert_no_dev_images(_service_images(prod_config))


def test_prod_all_mcp_services_resolve_to_main(prod_config):
    images = _service_images(prod_config)
    wrong = {
        name: image
        for name, image in images.items()
        if name in MCP_SERVICES and image != MAIN_IMAGE
    }
    assert not wrong, f"prod MCP services must use :main, got: {wrong}"


def test_prod_postgres_uses_pgvector_pg16(prod_config):
    assert _service_images(prod_config)["postgres"] == POSTGRES_IMAGE


def test_prod_domain_mcp_has_loopback_port(prod_config):
    domain = prod_config["services"]["domain-mcp"]
    loopback = [
        p for p in domain.get("ports", [])
        if p.get("host_ip") == "127.0.0.1" and p.get("published") == "8108"
    ]
    assert loopback, "domain-mcp prod override missing loopback 127.0.0.1:8108"


# ── SAIMON-STAGING-DEPLOY-FIX-2 / HARNESS-FIX-2 (2026-08-19) ──────────────
# The prior tag-only test missed the real bug: Compose MERGES `ports` by
# APPEND, so the loopback override did NOT remove the base `0.0.0.0:800X`
# binding — every MCP was double-bound (public + loopback). The override now
# uses `ports: !override` to REPLACE the base list, so the merged config must
# contain ZERO non-loopback bindings.

PUBLIC_HOST_IPS = (None, "0.0.0.0", "::")


def _public_bindings(config: dict) -> list[tuple[str, str]]:
    """Return [(service, published_port)] for any non-loopback host binding."""
    bad = []
    for name, svc in config.get("services", {}).items():
        for p in svc.get("ports", []):
            if p.get("host_ip") in PUBLIC_HOST_IPS:
                bad.append((name, p.get("published")))
    return bad


def test_staging_no_public_port_bindings(staging_config):
    bad = _public_bindings(staging_config)
    assert bad == [], f"staging merged config has public port bindings: {bad}"


def test_prod_no_public_port_bindings(prod_config):
    bad = _public_bindings(prod_config)
    assert bad == [], f"prod merged config has public port bindings: {bad}"


def test_domain_mcp_has_command_in_staging(staging_config):
    cmd = staging_config["services"]["domain-mcp"].get("command")
    assert cmd, "domain-mcp missing command in staging merge"
    assert "domain-mcp" in (cmd if isinstance(cmd, list) else [cmd])


def test_domain_mcp_has_command_in_prod(prod_config):
    cmd = prod_config["services"]["domain-mcp"].get("command")
    assert cmd, "domain-mcp missing command in prod merge"
    assert "domain-mcp" in (cmd if isinstance(cmd, list) else [cmd])
