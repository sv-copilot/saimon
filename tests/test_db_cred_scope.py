"""SAIMON-DB-CRED-SCOPE-1 (#221): no single shared POSTGRES_PASSWORD across MCP
containers.

Each MCP service must authenticate with its own DB role; the shared admin
``POSTGRES_PASSWORD`` must not appear in any MCP service's ``DATABASE_URL``.
Text-based regression test (PyYAML is not in ``requirements.txt``; ``docker``
is optional and not required for this test).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"

MCP_SERVICES = (
    "search-mcp",
    "generate-mcp",
    "export-mcp",
    "evaluate-mcp",
    "verify-mcp",
    "explore-mcp",
    "api-mcp",
    "domain-mcp",
    "crew-mcp",
)

_DB_URL_RE = re.compile(r"^\s+DATABASE_URL:\s*(.+?)\s*$")


def _database_urls(path: Path) -> dict[str, str]:
    """Map service name -> DATABASE_URL value by walking the compose text."""
    urls: dict[str, str] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        service_match = re.match(r"^  (\S+):\s*$", line)
        if service_match:
            current = service_match.group(1)
            continue
        if current is not None:
            url_match = _DB_URL_RE.match(line)
            if url_match:
                urls[current] = url_match.group(1)
    return urls


def _url_user(url: str) -> str:
    match = re.match(r"postgresql://([^:]+):", url)
    assert match, f"unexpected DATABASE_URL shape: {url!r}"
    return match.group(1)


def test_base_compose_mcp_services_do_not_use_shared_admin_credential() -> None:
    urls = _database_urls(BASE_COMPOSE)
    for service in MCP_SERVICES:
        assert service in urls, f"{service} missing DATABASE_URL in docker-compose.yml"
        assert "POSTGRES_PASSWORD" not in urls[service], (
            f"{service} still uses the shared POSTGRES_PASSWORD admin credential"
        )
        assert _url_user(urls[service]) != "saimon", (
            f"{service} still connects as the shared 'saimon' admin role"
        )


def test_base_compose_mcp_roles_are_distinct() -> None:
    urls = _database_urls(BASE_COMPOSE)
    users = [_url_user(urls[service]) for service in MCP_SERVICES]
    assert len(set(users)) == len(users), (
        f"MCP services must use distinct DB roles, got: {users}"
    )


def test_prod_compose_uses_per_service_database_urls() -> None:
    urls = _database_urls(PROD_COMPOSE)
    for service in MCP_SERVICES:
        assert service in urls, (
            f"{service} missing DATABASE_URL in docker-compose.prod.yml"
        )
        assert urls[service] != "${DATABASE_URL}", (
            f"{service} still uses the single shared DATABASE_URL env var"
        )
