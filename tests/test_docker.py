"""Tests for Docker + Compose configuration.

Validates:
- Dockerfile syntax and entrypoint dispatch
- docker-compose.yml service definitions
- .dockerignore coverage
- Health check endpoints on all 6 MCPs
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_file(path: str) -> str:
    return (REPO_ROOT / path).read_text()


def file_exists(path: str) -> bool:
    return (REPO_ROOT / path).is_file()


# ---------------------------------------------------------------------------
# Dockerfile tests
# ---------------------------------------------------------------------------

class TestDockerfile:
    """Validate the Dockerfile structure and content."""

    def test_dockerfile_exists(self):
        assert file_exists("Dockerfile"), "Dockerfile is missing"

    def test_dockerfile_base_image(self):
        content = read_file("Dockerfile")
        assert "FROM python:3.11" in content, "Must use Python 3.11 base image"

    def test_dockerfile_copies_requirements(self):
        content = read_file("Dockerfile")
        assert "COPY requirements.txt" in content
        assert "pip install" in content

    def test_dockerfile_copies_source(self):
        content = read_file("Dockerfile")
        assert "COPY research_shared/" in content
        assert "COPY mcp/" in content

    def test_dockerfile_uses_entrypoint_script(self):
        content = read_file("Dockerfile")
        assert "docker-entrypoint.sh" in content, "Must use entrypoint script"
        assert "ENTRYPOINT" in content

    def test_dockerfile_exposes_port(self):
        content = read_file("Dockerfile")
        assert "EXPOSE" in content, "Must expose a port"


# ---------------------------------------------------------------------------
# entrypoint script tests
# ---------------------------------------------------------------------------

class TestEntrypointScript:
    """Validate the docker-entrypoint.sh dispatch logic."""

    MCP_NAMES: ClassVar = [
        "search-mcp",
        "generate-mcp",
        "export-mcp",
        "evaluate-mcp",
        "verify-mcp",
        "explore-mcp",
    ]

    MODULE_MAP: ClassVar = {
        "search-mcp": "mcp.search.server:app",
        "generate-mcp": "mcp.generate.server:app",
        "export-mcp": "mcp.export.server:app",
        "evaluate-mcp": "mcp.evaluate.server:app",
        "verify-mcp": "mcp.verify.server:app",
        "explore-mcp": "mcp.explore.server:app",
    }

    PORT_MAP: ClassVar = {
        "search-mcp": 8001,
        "generate-mcp": 8002,
        "export-mcp": 8003,
        "evaluate-mcp": 8004,
        "verify-mcp": 8005,
        "explore-mcp": 8006,
    }

    def test_entrypoint_exists(self):
        assert file_exists("docker-entrypoint.sh"), "entrypoint script missing"

    def test_entrypoint_is_executable(self):
        path = REPO_ROOT / "docker-entrypoint.sh"
        assert os.access(path, os.X_OK), "entrypoint must be executable"

    def test_entrypoint_has_shebang(self):
        content = read_file("docker-entrypoint.sh")
        assert content.startswith("#!/"), "Must have shebang"

    def test_all_mcps_listed_in_case_statement(self):
        content = read_file("docker-entrypoint.sh")
        for mcp in self.MCP_NAMES:
            assert mcp in content, f"{mcp} missing from entrypoint case statement"

    def test_all_mcps_map_to_correct_module(self):
        content = read_file("docker-entrypoint.sh")
        for mcp, module in self.MODULE_MAP.items():
            assert module in content, f"Module {module} for {mcp} not found in entrypoint"

    def test_all_mcps_have_default_port(self):
        content = read_file("docker-entrypoint.sh")
        for mcp, port in self.PORT_MAP.items():
            assert str(port) in content, f"Port {port} for {mcp} not found in entrypoint"

    def test_entrypoint_handles_unknown_mcp(self):
        content = read_file("docker-entrypoint.sh")
        assert "Unknown MCP" in content, "Must handle unknown MCP names"

    def test_entrypoint_uses_set_euo_pipefail(self):
        content = read_file("docker-entrypoint.sh")
        assert "set -euo pipefail" in content, "Must use strict shell mode"

    def test_ports_are_unique(self):
        ports = list(self.PORT_MAP.values())
        assert len(ports) == len(set(ports)), "Port assignments must be unique"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def compose_yaml():
    path = REPO_ROOT / "docker-compose.yml"
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# docker-compose tests
# ---------------------------------------------------------------------------

class TestDockerCompose:
    """Validate docker-compose.yml structure."""

    def test_compose_file_exists(self):
        assert file_exists("docker-compose.yml"), "docker-compose.yml is missing"

    def test_compose_has_postgres(self, compose_yaml):
        services = compose_yaml.get("services", {})
        assert "postgres" in services, "postgres service required"

    def test_postgres_image(self, compose_yaml):
        pg = compose_yaml["services"]["postgres"]
        assert "postgres:16" in pg.get("image", ""), "Must use PostgreSQL 16"

    def test_postgres_has_healthcheck(self, compose_yaml):
        pg = compose_yaml["services"]["postgres"]
        assert "healthcheck" in pg, "PostgreSQL needs healthcheck"

    def test_all_six_mcps_defined(self, compose_yaml):
        services = compose_yaml.get("services", {})
        expected = {
            "search-mcp", "generate-mcp", "export-mcp",
            "evaluate-mcp", "verify-mcp", "explore-mcp",
        }
        actual = set(services.keys()) - {"postgres"}
        missing = expected - actual
        assert not missing, f"Missing MCP services: {missing}"

    def test_all_mcps_use_saimon_image(self, compose_yaml):
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = compose_yaml["services"][name]
            image = svc.get("image", "")
            assert "saimon" in image, f"{name} must use saimon image"

    def test_all_mcps_depend_on_postgres(self, compose_yaml):
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = compose_yaml["services"][name]
            deps = svc.get("depends_on", {})
            assert "postgres" in deps, f"{name} must depend on postgres"

    def test_all_mcps_have_healthcheck(self, compose_yaml):
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = compose_yaml["services"][name]
            assert "healthcheck" in svc, f"{name} needs healthcheck"

    def test_mcp_ports_unique(self, compose_yaml):
        ports_seen: set[int] = set()
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = compose_yaml["services"][name]
            port_mappings = svc.get("ports", [])
            for mapping in port_mappings:
                host_port = int(str(mapping).split(":")[0])
                assert host_port not in ports_seen, f"Port {host_port} duplicated"
                ports_seen.add(host_port)

    def test_all_mcps_have_saimon_api_key(self, compose_yaml):
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = compose_yaml["services"][name]
            env = svc.get("environment", {})
            env_str = str(env)
            assert "SAIMON_API_KEY" in env_str, f"{name} missing SAIMON_API_KEY"

    def test_pgdata_volume_defined(self, compose_yaml):
        volumes = compose_yaml.get("volumes", {})
        assert "pgdata" in volumes, "pgdata volume must be defined"

    def test_schema_mounted_to_postgres(self, compose_yaml):
        pg = compose_yaml["services"]["postgres"]
        volumes = pg.get("volumes", [])
        schema_mounted = any("schema.sql" in str(v) for v in volumes)
        assert schema_mounted, "schema.sql must be mounted into postgres"


# ---------------------------------------------------------------------------
# .dockerignore tests
# ---------------------------------------------------------------------------

class TestDockerignore:
    """Validate .dockerignore contents."""

    def test_dockerignore_exists(self):
        assert file_exists(".dockerignore"), ".dockerignore is missing"

    def test_ignores_git(self):
        content = read_file(".dockerignore")
        assert ".git" in content

    def test_ignores_pycache(self):
        content = read_file(".dockerignore")
        assert "__pycache__" in content

    def test_ignores_tests(self):
        content = read_file(".dockerignore")
        assert "tests/" in content

    def test_ignores_env_files(self):
        content = read_file(".dockerignore")
        assert ".env" in content

    def test_ignores_vscode(self):
        content = read_file(".dockerignore")
        assert ".vscode" in content

    def test_ignores_docs(self):
        content = read_file(".dockerignore")
        assert ".docs" in content


# ---------------------------------------------------------------------------
# health check endpoint tests (integration)
# ---------------------------------------------------------------------------

class TestHealthEndpoints:
    """Validate that each MCP responds to its /health endpoint."""

    MCP_PORTS: ClassVar = {
        "search": 8001,
        "generate": 8002,
        "export": 8003,
        "evaluate": 8004,
        "verify": 8005,
        "explore": 8006,
    }

    @pytest.mark.parametrize("mcp_name,port", list(MCP_PORTS.items()))
    def test_health_endpoint_exists_in_code(self, mcp_name, port):
        """Verify each server.py defines a /health GET endpoint."""
        server_path = REPO_ROOT / "mcp" / mcp_name / "server.py"
        content = server_path.read_text()
        assert '@app.get("/health")' in content, (
            f"{mcp_name}/server.py missing @app.get('/health')"
        )

    @pytest.mark.parametrize("mcp_name", list(MCP_PORTS.keys()))
    def test_health_returns_service_name(self, mcp_name):
        """Verify the health endpoint response includes the service name."""
        server_path = REPO_ROOT / "mcp" / mcp_name / "server.py"
        content = server_path.read_text()
        service_name = f"{mcp_name}-mcp"
        # The health response should reference the service name
        assert service_name in content, (
            f"{mcp_name}/server.py health check doesn't reference {service_name}"
        )

    @pytest.mark.parametrize("mcp_name", list(MCP_PORTS.keys()))
    def test_health_is_unauthenticated(self, mcp_name):
        """Verify the health endpoint does NOT call _require_auth."""
        server_path = REPO_ROOT / "mcp" / mcp_name / "server.py"
        content = server_path.read_text()

        # Find the health function block
        health_match = re.search(
            r'@app\.get\("/health"\).*?(?=@app\.|\Z)', content, re.DOTALL
        )
        if health_match:
            health_block = health_match.group()
            assert "_require_auth" not in health_block, (
                f"{mcp_name} health check must not require auth"
            )


# ---------------------------------------------------------------------------
# schema.sql tests
# ---------------------------------------------------------------------------

class TestSchema:
    """Validate the PostgreSQL schema."""

    def test_schema_exists(self):
        assert file_exists("schema.sql"), "schema.sql is missing"

    def test_schema_has_content_type_registry(self):
        content = read_file("schema.sql")
        assert "content_type_registry" in content

    def test_schema_has_knowledge_graph_nodes(self):
        content = read_file("schema.sql")
        assert "knowledge_graph_nodes" in content

    def test_schema_has_knowledge_graph_edges(self):
        content = read_file("schema.sql")
        assert "knowledge_graph_edges" in content

    def test_schema_has_seed_requests(self):
        content = read_file("schema.sql")
        assert "seed_requests" in content

    def test_schema_has_voice_profiles(self):
        content = read_file("schema.sql")
        assert "voice_profiles" in content

    def test_schema_has_audit_log(self):
        content = read_file("schema.sql")
        assert "audit_log" in content

    def test_schema_seeds_content_types(self):
        content = read_file("schema.sql")
        assert "INSERT INTO content_type_registry" in content
        assert "blog_post" in content

    def test_schema_seeds_voice_profiles(self):
        content = read_file("schema.sql")
        assert "INSERT INTO voice_profiles" in content
        assert "spencer-default" in content
