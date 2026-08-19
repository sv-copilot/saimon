"""Packaging regression tests (HARNESS-FIX-3, 2026-08-19).

The Dockerfile previously omitted ``COPY plugins/ plugins/``, so ``domain-mcp``
ran in prod with ``plugins: 0`` (the legal plugin silently never loaded). These
tests build the image and prove the plugin is packaged and exposes ``PLUGIN``.

Building the full image is slow (~pip install), so the test is gated behind:
- ``docker`` being available, AND
- ``SAIMON_RUN_DOCKER_BUILD=1`` (opt-in — run explicitly, e.g. in a packaging
  CI job, not on every local ``pytest`` run).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

IMAGE_TAG = "saimon:packaging-test"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _build_enabled() -> bool:
    return os.environ.get("SAIMON_RUN_DOCKER_BUILD", "") == "1"


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="docker not installed"
)


@pytest.fixture(scope="module")
def built_image():
    """Build the image once for the module and yield the image tag."""
    if not _build_enabled():
        pytest.skip("SAIMON_RUN_DOCKER_BUILD=1 not set — skipping slow build")
    proc = subprocess.run(
        ["docker", "build", "-q", "-t", IMAGE_TAG, str(REPO_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"docker build failed:\n{proc.stderr[-2000:]}")
    yield IMAGE_TAG
    subprocess.run(["docker", "rmi", "-f", IMAGE_TAG], capture_output=True)


def _run_in_image(image: str, code: str) -> subprocess.CompletedProcess:
    # The image ENTRYPOINT is docker-entrypoint.sh (MCP dispatcher); override it
    # so we can run arbitrary python for the packaging assertion.
    return subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python3", image, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


def test_image_contains_plugins_legal(built_image):
    """The built image packages ``/app/plugins/legal/__init__.py``."""
    proc = _run_in_image(
        built_image,
        "from pathlib import Path; print(Path('/app/plugins/legal/__init__.py').exists())",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "True"


def test_image_exposes_legal_plugin(built_image):
    """``plugins.legal`` imports and exposes ``PLUGIN`` (a DomainPlugin)."""
    proc = _run_in_image(
        built_image,
        "import plugins.legal; print(hasattr(plugins.legal, 'PLUGIN')); "
        "print(plugins.legal.PLUGIN.domain)",
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert lines[0] == "True"
    assert lines[1] == "legal"


def test_dockerfile_copies_plugins_dir():
    """Source-level guard: Dockerfile must COPY plugins/ (fast, no build)."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "COPY plugins/ plugins/" in content


def test_dockerignore_does_not_exclude_plugins():
    """`.dockerignore` must not exclude the plugins directory."""
    ignores = (REPO_ROOT / ".dockerignore").read_text().splitlines()
    excluded = [line.strip() for line in ignores if line.strip().rstrip("/") == "plugins"]
    assert not excluded, ".dockerignore excludes plugins/"
