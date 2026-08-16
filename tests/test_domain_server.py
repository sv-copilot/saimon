"""Tests for domain-mcp — the domain plugin server + tool router.

The domain server loads registered domain plugins and routes ``domain.*``
tool calls to them.  These tests pin that behaviour without any real plugins
installed: a fixture plugin is registered via a test ``_PLUGIN_PATHS``
override, a missing plugin path must log (not crash), and unknown
domain/tool references must return an error envelope.
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from research_shared.domain_plugin import DomainPlugin

# ---------------------------------------------------------------------------
# fixture plugin
# ---------------------------------------------------------------------------


class EchoTool:
    """A minimal structural DomainTool that echoes its arguments."""

    name = "echo"
    description = "Echo back the provided arguments."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"echoed": arguments.get("message", ""), "arguments": arguments}


class FakeAdapter:
    """A minimal SourceIndexAdapter-shaped object."""

    name = "fake_index"
    tier = "S"
    trust_model = "institutional"

    async def search(self, query: str, limit: int = 10, offset: int = 0) -> list:
        return []

    async def resolve_doi(self, doi: str):
        return None


class FakePlugin(DomainPlugin):
    """A concrete plugin used to exercise the loader + router."""

    domain = "fake"

    def adapters(self) -> list:
        return [FakeAdapter()]

    def content_types(self) -> list:
        return [{"name": "fake:widget", "description": "A fake widget type."}]

    def tools(self) -> list:
        return [EchoTool()]


def _install_fake_plugin_module() -> str:
    """Register a synthetic module exposing ``PLUGIN`` and return its path."""
    mod = types.ModuleType("_domain_test.fake_plugin")
    mod.PLUGIN = FakePlugin()
    sys.modules["_domain_test.fake_plugin"] = mod
    return "_domain_test.fake_plugin"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_key() -> str:
    return "sk-test-domain-key"


@pytest.fixture
def server(api_key, monkeypatch):
    """Import a fresh domain-mcp server module with no plugins configured."""
    monkeypatch.setenv("SAIMON_API_KEY", api_key)
    monkeypatch.setenv("SAIMON_DOMAIN_PLUGIN_PATHS", "")
    sys.modules.pop("mcp.domain.server", None)
    from mcp.domain import server as srv

    return srv


@pytest.fixture
def client(server) -> TestClient:
    return TestClient(server.app)


@pytest.fixture
def auth_headers(api_key) -> dict[str, str]:
    return {"X-Saimon-API-Key": api_key}


@pytest.fixture
def sample_trace_id() -> str:
    return str(uuid.uuid4())


def _call_payload(trace_id: str, tool: str, arguments: dict | None = None) -> dict:
    return {
        "trace_id": trace_id,
        "content_type": "domain",
        "parameters": {"tool": tool, "arguments": arguments or {}},
    }


# ---------------------------------------------------------------------------
# health / auth
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "domain-mcp"


class TestAuth:
    def test_tool_endpoint_rejects_missing_key(self, client, sample_trace_id):
        response = client.post(
            "/tools/call",
            json=_call_payload(sample_trace_id, "fake.echo"),
        )
        assert response.status_code == 401

    def test_tool_endpoint_rejects_wrong_key(self, client, sample_trace_id):
        response = client.post(
            "/tools/call",
            json=_call_payload(sample_trace_id, "fake.echo"),
            headers={"X-Saimon-API-Key": "wrong-key"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# plugin loader
# ---------------------------------------------------------------------------


class TestPluginLoader:
    def test_loads_registered_plugin(self, server):
        path = _install_fake_plugin_module()
        loaded = server._load_plugins([path])
        assert "fake" in loaded

    def test_registers_adapters_and_content_types(self, server):
        path = _install_fake_plugin_module()
        server._load_plugins([path])
        from research_shared.shadow_registry import get_shadow_registry

        registry = get_shadow_registry()
        assert registry.get("fake_index") is not None
        assert any(ct["name"] == "fake:widget" for ct in server._content_types)

    def test_missing_plugin_path_logs_not_installed(self, server, caplog):
        with caplog.at_level("INFO", logger="saimon.domain"):
            loaded = server._load_plugins(["not.a.real.module.path"])
        assert loaded == {}
        assert "not installed" in caplog.text

    def test_module_without_plugin_is_skipped(self, server, caplog):
        mod = types.ModuleType("_domain_test.no_plugin")
        sys.modules["_domain_test.no_plugin"] = mod
        with caplog.at_level("INFO", logger="saimon.domain"):
            loaded = server._load_plugins(["_domain_test.no_plugin"])
        assert loaded == {}
        assert "not installed" in caplog.text


# ---------------------------------------------------------------------------
# tool routing
# ---------------------------------------------------------------------------


class TestToolRouting:
    @pytest.fixture(autouse=True)
    def _install_plugin(self, server):
        server._load_plugins([_install_fake_plugin_module()])
        yield

    def test_routes_domain_tool(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/call",
            json=_call_payload(sample_trace_id, "fake.echo", {"message": "hi"}),
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["echoed"] == "hi"

    def test_unknown_domain_returns_error(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/call",
            json=_call_payload(sample_trace_id, "missing.echo"),
            headers=auth_headers,
        )
        body = response.json()
        assert body["status"] == "error"
        assert any("Unknown domain" in e for e in body["errors"])

    def test_unknown_tool_returns_error(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/call",
            json=_call_payload(sample_trace_id, "fake.nope"),
            headers=auth_headers,
        )
        body = response.json()
        assert body["status"] == "error"
        assert any("Unknown" in e for e in body["errors"])

    def test_missing_tool_parameter_returns_error(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/call",
            json={
                "trace_id": sample_trace_id,
                "content_type": "domain",
                "parameters": {"arguments": {}},
            },
            headers=auth_headers,
        )
        body = response.json()
        assert body["status"] == "error"
        assert any("tool" in e for e in body["errors"])


# ---------------------------------------------------------------------------
# helper tools (MCP minimums)
# ---------------------------------------------------------------------------


class TestHelperTools:
    def test_onboard_reports_ready(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/onboard",
            json={"trace_id": sample_trace_id, "content_type": "domain", "parameters": {}},
            headers=auth_headers,
        )
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["server_name"] == "domain-mcp"
        assert body["data"]["readiness"]["status"] == "ready"

    def test_vignette_has_steps(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/vignette",
            json={"trace_id": sample_trace_id, "content_type": "domain", "parameters": {}},
            headers=auth_headers,
        )
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["steps"]

    def test_feedback_returns_queue_id(self, client, sample_trace_id, auth_headers):
        response = client.post(
            "/tools/feedback",
            json={
                "trace_id": sample_trace_id,
                "content_type": "domain",
                "parameters": {
                    "type": "bug",
                    "message": "domain tool routed to wrong plugin",
                    "system_data": {"SAIMON_API_KEY": "sk-secret-value"},
                },
            },
            headers=auth_headers,
        )
        body = response.json()
        assert body["status"] == "success"
        assert body["data"]["queue_id"]
        # secret values must be scrubbed before logging/storage
        assert "sk-secret-value" not in str(body)
