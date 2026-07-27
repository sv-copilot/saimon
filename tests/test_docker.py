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


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — Dockerfile hardening
# ---------------------------------------------------------------------------

class TestDockerfileHardening:
    """Validate Dockerfile production hardening additions."""

    def test_dockerfile_has_stopsignal(self):
        content = read_file("Dockerfile")
        assert "STOPSIGNAL" in content, "Dockerfile must define STOPSIGNAL"

    def test_dockerfile_stopsignal_is_sigterm(self):
        content = read_file("Dockerfile")
        assert "STOPSIGNAL SIGTERM" in content, "STOPSIGNAL must be SIGTERM"

    def test_dockerfile_has_healthcheck_instruction(self):
        content = read_file("Dockerfile")
        assert "HEALTHCHECK" in content, "Dockerfile must have HEALTHCHECK"


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — entrypoint hardening
# ---------------------------------------------------------------------------

class TestEntrypointHardening:
    """Validate entrypoint graceful shutdown additions."""

    def test_entrypoint_has_graceful_shutdown(self):
        content = read_file("docker-entrypoint.sh")
        assert "--timeout-graceful-shutdown" in content, (
            "entrypoint must pass --timeout-graceful-shutdown to uvicorn"
        )


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — production compose
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def prod_compose_yaml():
    path = REPO_ROOT / "docker-compose.prod.yml"
    with open(path) as f:
        return yaml.safe_load(f)


class TestProductionCompose:
    """Validate docker-compose.prod.yml structure."""

    def test_prod_compose_exists(self):
        assert file_exists("docker-compose.prod.yml"), (
            "docker-compose.prod.yml is missing"
        )

    def test_prod_compose_has_all_mcps(self, prod_compose_yaml):
        services = prod_compose_yaml.get("services", {})
        expected = {
            "postgres", "search-mcp", "generate-mcp", "export-mcp",
            "evaluate-mcp", "verify-mcp", "explore-mcp",
        }
        assert set(services.keys()) == expected

    def test_prod_services_restart_always(self, prod_compose_yaml):
        for name, svc in prod_compose_yaml["services"].items():
            restart = svc.get("restart", "")
            assert restart == "always", f"{name} must have restart: always in prod"

    def test_prod_services_have_resource_limits(self, prod_compose_yaml):
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = prod_compose_yaml["services"][name]
            deploy = svc.get("deploy", {})
            resources = deploy.get("resources", {})
            assert "limits" in resources, f"{name} missing resource limits"
            assert "reservations" in resources, f"{name} missing resource reservations"

    def test_prod_services_have_logging(self, prod_compose_yaml):
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = prod_compose_yaml["services"][name]
            logging = svc.get("logging", {})
            assert "driver" in logging, f"{name} missing logging driver"

    def test_prod_has_saimon_env_production(self, prod_compose_yaml):
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = prod_compose_yaml["services"][name]
            env = svc.get("environment", {})
            env_str = str(env)
            assert "SAIMON_ENV" in env_str, f"{name} missing SAIMON_ENV in prod"

    def test_prod_no_default_saimon_api_key(self, prod_compose_yaml):
        """Production compose must not have default dev API keys."""
        for name in ["search-mcp", "generate-mcp", "export-mcp",
                     "evaluate-mcp", "verify-mcp", "explore-mcp"]:
            svc = prod_compose_yaml["services"][name]
            env = svc.get("environment", {})
            env_str = str(env)
            assert "sk-test-" not in env_str, (
                f"{name} must not use default test API key in prod"
            )


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — .env.example
# ---------------------------------------------------------------------------

class TestEnvExample:
    """Validate .env.example template."""

    def test_env_example_exists(self):
        assert file_exists(".env.example"), ".env.example is missing"

    def test_env_example_has_saimon_api_key(self):
        content = read_file(".env.example")
        assert "SAIMON_API_KEY" in content

    def test_env_example_has_database_url(self):
        content = read_file(".env.example")
        assert "DATABASE_URL" in content

    def test_env_example_has_deepseek_api_key(self):
        content = read_file(".env.example")
        assert "DEEPSEEK_API_KEY" in content

    def test_env_example_has_saimon_env(self):
        content = read_file(".env.example")
        assert "SAIMON_ENV" in content

    def test_env_example_warns_not_to_commit(self):
        content = read_file(".env.example")
        assert "Never commit" in content or "never commit" in content.lower()


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — CI workflow
# ---------------------------------------------------------------------------

class TestCIWorkflow:
    """Validate .github/workflows/ci.yml."""

    @property
    def ci_path(self) -> str:
        return ".github/workflows/ci.yml"

    def test_ci_workflow_exists(self):
        assert file_exists(self.ci_path), "CI workflow is missing"

    def test_ci_has_test_job(self):
        content = read_file(self.ci_path)
        assert "pytest" in content, "CI must run pytest"

    def test_ci_has_lint_job(self):
        content = read_file(self.ci_path)
        assert "ruff" in content, "CI must run ruff"

    def test_ci_has_docker_build(self):
        content = read_file(self.ci_path)
        assert "docker" in content.lower(), "CI must build Docker image"

    def test_ci_uses_python_311(self):
        content = read_file(self.ci_path)
        assert "3.11" in content, "CI must use Python 3.11"

    def test_ci_triggers_on_push(self):
        content = read_file(self.ci_path)
        assert "push" in content, "CI must trigger on push"

    def test_ci_triggers_on_pr(self):
        content = read_file(self.ci_path)
        assert "pull_request" in content, "CI must trigger on pull_request"


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — deep health checks
# ---------------------------------------------------------------------------

class TestDeepHealthChecks:
    """Validate enhanced /health endpoints with backend status checks."""

    MCP_NAMES: ClassVar = [
        "search", "generate", "export", "evaluate", "verify", "explore",
    ]

    @pytest.mark.parametrize("mcp_name", MCP_NAMES)
    def test_health_has_checks_field(self, mcp_name):
        """Verify /health response includes a 'checks' dict."""
        server_path = REPO_ROOT / "mcp" / mcp_name / "server.py"
        content = server_path.read_text()
        assert '"checks"' in content, (
            f"{mcp_name}/server.py health must include 'checks' field"
        )

    def test_search_health_checks_database(self):
        content = read_file("mcp/search/server.py")
        assert "database" in content.lower(), (
            "search health must report database status"
        )

    def test_generate_health_checks_llm_and_db(self):
        content = read_file("mcp/generate/server.py")
        assert "llm" in content.lower(), (
            "generate health must report LLM status"
        )
        assert "database" in content.lower(), (
            "generate health must report database status"
        )

    def test_export_health_reports_stateless(self):
        content = read_file("mcp/export/server.py")
        assert "stateless" in content.lower(), (
            "export health must report stateless backend"
        )

    def test_evaluate_health_checks_llm(self):
        content = read_file("mcp/evaluate/server.py")
        assert "llm" in content.lower(), (
            "evaluate health must report LLM status"
        )

    def test_verify_health_checks_llm(self):
        content = read_file("mcp/verify/server.py")
        assert "llm" in content.lower(), (
            "verify health must report LLM status"
        )

    def test_explore_health_checks_database(self):
        content = read_file("mcp/explore/server.py")
        assert "database" in content.lower(), (
            "explore health must report database status"
        )


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — lifespan module
# ---------------------------------------------------------------------------

class TestLifespanModule:
    """Validate research_shared/lifespan.py."""

    def test_lifespan_module_exists(self):
        path = REPO_ROOT / "research_shared" / "lifespan.py"
        assert path.is_file(), "lifespan.py is missing"

    def test_lifespan_exports_build_lifespan(self):
        from research_shared.lifespan import build_lifespan
        assert callable(build_lifespan)

    def test_build_lifespan_returns_callable(self):
        from research_shared.lifespan import build_lifespan
        result = build_lifespan("test-mcp")
        assert callable(result)


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — secrets module
# ---------------------------------------------------------------------------

class TestSecretsModule:
    """Validate research_shared/secrets.py is importable."""

    def test_secrets_module_exists(self):
        path = REPO_ROOT / "research_shared" / "secrets.py"
        assert path.is_file(), "secrets.py is missing"

    def test_secrets_exports_config(self):
        from research_shared.secrets import SecretsConfig
        assert SecretsConfig is not None

    def test_secrets_exports_validation_result(self):
        from research_shared.secrets import ValidationResult
        assert ValidationResult is not None


# ---------------------------------------------------------------------------
# DEPLOY-HARDEN-1 tests — all servers use lifespan
# ---------------------------------------------------------------------------

class TestAllServersUseLifespan:
    """Validate every MCP server imports and uses build_lifespan."""

    MCP_NAMES: ClassVar = [
        "search", "generate", "export", "evaluate", "verify", "explore",
    ]

    @pytest.mark.parametrize("mcp_name", MCP_NAMES)
    def test_server_imports_lifespan(self, mcp_name):
        server_path = REPO_ROOT / "mcp" / mcp_name / "server.py"
        content = server_path.read_text()
        assert "build_lifespan" in content, (
            f"{mcp_name}/server.py must import build_lifespan"
        )

    @pytest.mark.parametrize("mcp_name", MCP_NAMES)
    def test_server_passes_lifespan_to_fastapi(self, mcp_name):
        server_path = REPO_ROOT / "mcp" / mcp_name / "server.py"
        content = server_path.read_text()
        assert "lifespan=" in content, (
            f"{mcp_name}/server.py must pass lifespan= to FastAPI()"
        )
