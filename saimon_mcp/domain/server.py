"""server.py — domain-mcp FastAPI application.

A seventh MCP that loads registered domain plugins at startup and routes
``domain.*`` tool calls to them.  Unlike the six core MCPs, this server owns
no domain logic: it composes plugins that each contribute adapters, content
types, and tools through the ``DomainPlugin`` contract.

Design invariants:

- A missing plugin is a log line, never a crash.
- Plugin adapters register into the shared shadow registry; plugin content
  types register into the server's content-type view.
- ``POST /tools/call`` dispatches ``{domain}.{tool}`` to the owning plugin.
- Auth is fail-closed and audit follows the other six servers.
"""

from __future__ import annotations

import importlib
import logging
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.adapters.base import SourceIndexAdapter
from research_shared.archive_registry import (
    get_archive_registry,
    reset_archive_registry,
)
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.db import DatabasePool
from research_shared.domain_plugin import DomainPlugin
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.hardening import apply_hardening, build_audit_logger
from research_shared.lifespan import build_lifespan

logger = logging.getLogger("saimon.domain")

# ---------------------------------------------------------------------------
# backend injection (must be before lifespan)
# ---------------------------------------------------------------------------

_db_pool: DatabasePool | None = None


def set_db_pool(pool: DatabasePool | None) -> None:
    """Inject a DatabasePool for plugins that query the knowledge graph."""
    global _db_pool
    _db_pool = pool


# ---------------------------------------------------------------------------
# plugin state
# ---------------------------------------------------------------------------

_plugins: dict[str, DomainPlugin] = {}
_content_types: list[dict[str, Any]] = []


def _default_plugin_paths() -> list[str]:
    """Plugin module paths from ``SAIMON_DOMAIN_PLUGIN_PATHS`` (comma-separated)."""
    raw = os.getenv("SAIMON_DOMAIN_PLUGIN_PATHS", "")
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


_PLUGIN_PATHS: list[str] = _default_plugin_paths()


# ---------------------------------------------------------------------------
# plugin loading
# ---------------------------------------------------------------------------


def _register_plugin(plugin: DomainPlugin) -> None:
    """Register a plugin's adapters and content types into the shared registries."""
    _plugins[plugin.domain] = plugin

    registry = get_archive_registry()
    for adapter in plugin.adapters():
        name = getattr(adapter, "name", None)
        if name and isinstance(adapter, SourceIndexAdapter):
            registry.register(adapter)
        elif name:
            # Protocol can be duck-typed; register by name as long as it's sane.
            registry.register(adapter)

    for content_type in plugin.content_types():
        if isinstance(content_type, dict) and "name" in content_type:
            _content_types.append(content_type)


def _load_plugins(paths: list[str] | None = None) -> dict[str, DomainPlugin]:
    """Load plugins from dotted module paths.

    Each module must expose a ``PLUGIN`` attribute that is a ``DomainPlugin``.
    A path that cannot be imported (or lacks a valid ``PLUGIN``) is logged
    "not installed" and skipped — never fatal.

    Args:
        paths: Explicit module paths.  When None, ``_PLUGIN_PATHS`` is used.

    Returns:
        Mapping of ``domain`` -> loaded ``DomainPlugin``.
    """
    targets = _PLUGIN_PATHS if paths is None else paths

    # Rebuild registration state so repeated loads are idempotent.
    _plugins.clear()
    _content_types.clear()
    reset_archive_registry()

    loaded: dict[str, DomainPlugin] = {}
    for path in targets:
        if not path:
            continue
        try:
            module = importlib.import_module(path)
        except ImportError as exc:
            logger.info("domain plugin %r not installed: %s", path, exc)
            continue

        plugin = getattr(module, "PLUGIN", None)
        if not isinstance(plugin, DomainPlugin):
            logger.info(
                "domain plugin %r not installed: module exposes no PLUGIN "
                "(DomainPlugin instance)",
                path,
            )
            continue

        _register_plugin(plugin)
        loaded[plugin.domain] = plugin

    logger.info(
        "domain-mcp loaded %d plugin(s), %d content type(s)",
        len(loaded),
        len(_content_types),
    )
    return loaded


def _find_tool(plugin: DomainPlugin, tool_name: str, full_ref: str):
    """Return the tool with *tool_name* in *plugin*, or None."""
    for tool in plugin.tools():
        name = getattr(tool, "name", None)
        if name in (tool_name, full_ref):
            return tool
    return None


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan(
    "domain-mcp",
    db_pool_ref=lambda: _db_pool,
    db_pool_setter=set_db_pool,
)
app = FastAPI(title="domain-mcp", version="0.1.0", lifespan=_lifespan)

# SAIMON-DOMAIN-PLUGIN-LOAD-1: wire plugin loading at startup. The loader was
# previously defined but never invoked, so the server ran with an empty plugin
# registry (staging showed plugins: 0 and legal.* calls returned
# "Unknown domain plugin"). Load at module import so plugins register before
# any request is served. Missing/typo'd modules are logged "not installed" and
# never crash startup (existing fail-safe).
_load_plugins()

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)
apply_hardening(app, _auth)


def _require_auth(request: Request) -> None:
    """Fail-closed auth guard (FastAPI dependency)."""
    if _auth.has_api_key:
        key = _auth.extract_from_headers(dict(request.headers))
        try:
            _auth.validate(key)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


# ---------------------------------------------------------------------------
# envelope helpers
# ---------------------------------------------------------------------------


def _ok(trace_id: str, data: Any = None) -> ResearchResponse:
    return ResearchResponse(trace_id=trace_id, status="success", data=data)


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(trace_id=trace_id, status="error", errors=[message])


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    """Unauthenticated health check."""
    db_ok = False
    if _db_pool is not None:
        try:
            await _db_pool.fetch("SELECT 1")
            db_ok = True
        except Exception:
            logger.debug("domain-mcp health: DB not reachable", exc_info=True)
    return {
        "status": "ok",
        "service": "domain-mcp",
        "checks": {
            "database": "connected" if db_ok else "unavailable",
            "plugins": len(_plugins),
            "content_types": len(_content_types),
        },
    }


# ---------------------------------------------------------------------------
# tool manifest
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "call",
        "description": "Route a domain.* tool call to a registered plugin.",
        "parameters": {
            "tool": "str (required, format 'domain.tool_name')",
            "arguments": "dict (optional)",
        },
    },
    {
        "name": "list_plugins",
        "description": "List loaded domain plugins and their registered tools.",
        "parameters": {},
    },
    {
        "name": "list_content_types",
        "description": "List content types contributed by loaded plugins.",
        "parameters": {},
    },
    {
        "name": "onboard",
        "description": "Start a session: describe the server and its readiness.",
        "parameters": {},
    },
    {
        "name": "vignette",
        "description": "Demonstrate one end-to-end domain plugin use case.",
        "parameters": {},
    },
    {
        "name": "feedback",
        "description": "Accept operator feedback without leaving the session.",
        "parameters": {
            "type": "str (optional, 'bug'|'feature'|'question')",
            "message": "str (optional)",
            "system_data": "dict (optional, scrubbed)",
            "usecase_data": "dict (optional, scrubbed)",
        },
    },
]


@app.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """Return the tool manifest for this MCP."""
    _require_auth(request)
    return {"tools": _TOOLS}


# ---------------------------------------------------------------------------
# tool: call (dynamic domain.* router)
# ---------------------------------------------------------------------------


@app.post("/tools/call")
async def call_tool(payload: ResearchRequest, request: Request) -> ResearchResponse:
    _require_auth(request)

    tool_ref = payload.parameters.get("tool")
    if not tool_ref:
        return _error(payload.trace_id, "Parameter 'tool' is required.")

    audit = build_audit_logger(payload, request, _auth, "domain-mcp")
    audit.log_request(content_type=payload.content_type, tool=tool_ref)

    domain, sep, tool_name = str(tool_ref).partition(".")
    if not sep:
        resp = _error(
            payload.trace_id,
            f"Malformed tool reference: '{tool_ref}' (expected 'domain.tool')",
        )
        audit.log_response(status=resp.status)
        return resp

    plugin = _plugins.get(domain)
    if plugin is None:
        resp = _error(payload.trace_id, f"Unknown domain plugin: '{domain}'")
        audit.log_response(status=resp.status)
        return resp

    tool = _find_tool(plugin, tool_name, str(tool_ref))
    if tool is None:
        resp = _error(payload.trace_id, f"Unknown domain tool: '{tool_ref}'")
        audit.log_response(status=resp.status)
        return resp

    arguments = payload.parameters.get("arguments") or {}
    if not isinstance(arguments, dict):
        resp = _error(payload.trace_id, "Parameter 'arguments' must be an object.")
        audit.log_response(status=resp.status)
        return resp

    try:
        result = await tool.execute(arguments)
    except Exception as exc:
        logger.exception("domain tool %r failed", tool_ref)
        resp = _error(payload.trace_id, f"Tool execution failed: {exc}")
        audit.log_response(status=resp.status)
        return resp

    resp = _ok(payload.trace_id, data=result)
    audit.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: list_plugins
# ---------------------------------------------------------------------------


@app.post("/tools/list_plugins")
async def list_plugins(payload: ResearchRequest, request: Request) -> ResearchResponse:
    _require_auth(request)
    data = {
        "plugins": [
            {
                "domain": domain,
                "tools": [getattr(t, "name", None) for t in plugin.tools()],
                "adapters": [getattr(a, "name", None) for a in plugin.adapters()],
            }
            for domain, plugin in sorted(_plugins.items())
        ]
    }
    return _ok(payload.trace_id, data=data)


# ---------------------------------------------------------------------------
# tool: list_content_types
# ---------------------------------------------------------------------------


@app.post("/tools/list_content_types")
async def list_content_types(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)
    return _ok(payload.trace_id, data={"content_types": list(_content_types)})


# ---------------------------------------------------------------------------
# helper tools (MCP minimums)
# ---------------------------------------------------------------------------


def _aggregate_readiness() -> dict[str, Any]:
    """Aggregate per-plugin readiness into a single readiness report."""
    missing: list[str] = []
    for plugin in _plugins.values():
        rd = getattr(plugin, "readiness", None)
        if callable(rd):
            rd = rd()
        if isinstance(rd, dict) and rd.get("status") == "missing_config":
            missing.append(str(rd.get("details", plugin.domain)))
    if missing:
        return {
            "status": "missing_config",
            "details": "; ".join(missing),
        }
    return {
        "status": "ready",
        "details": f"{len(_plugins)} plugin(s), {len(_content_types)} content type(s) loaded",
    }


@app.post("/tools/onboard")
async def onboard(payload: ResearchRequest, request: Request) -> ResearchResponse:
    _require_auth(request)
    data = {
        "server_name": "domain-mcp",
        "version": "0.1.0",
        "description": (
            "Loads registered domain plugins and routes domain.* tool calls "
            "to them. Plugins contribute source adapters, content types, and "
            "tools through the DomainPlugin contract."
        ),
        "prerequisites": [
            "SAIMON_API_KEY",
            "SAIMON_DOMAIN_PLUGIN_PATHS (comma-separated plugin module paths)",
        ],
        "docs_links": ["../docs/", "research_shared/domain_plugin.py"],
        "recommended_first_steps": [
            "Set SAIMON_DOMAIN_PLUGIN_PATHS to a comma-separated list of plugin module paths",
            "Start the server and confirm /health shows the expected plugin count",
            "Call POST /tools/call with {'tool': '<domain>.<tool>'}",
        ],
        "readiness": _aggregate_readiness(),
    }
    return _ok(payload.trace_id, data=data)


@app.post("/tools/vignette")
async def vignette(payload: ResearchRequest, request: Request) -> ResearchResponse:
    _require_auth(request)
    data = {
        "title": "Register a domain plugin and call a domain.* tool",
        "description": (
            "Walks through loading one plugin module and invoking one of its "
            "tools through the domain-mcp router."
        ),
        "steps": [
            {
                "step": 1,
                "action": "Write a module that exposes PLUGIN = MyPlugin()",
                "expected": "MyPlugin subclasses DomainPlugin with a domain, adapters(), content_types(), tools()",
            },
            {
                "step": 2,
                "action": "Set SAIMON_DOMAIN_PLUGIN_PATHS=my_pkg.plugin",
                "expected": "The plugin loads at startup; a missing module is logged 'not installed', not a crash",
            },
            {
                "step": 3,
                "action": "POST /tools/call with parameters {'tool': '<domain>.<tool>', 'arguments': {...}}",
                "expected": "A success envelope with the tool's result in 'data'",
            },
        ],
        "output_example": (
            '{"trace_id": "...", "status": "success", '
            '"data": {"echoed": "hi", "arguments": {"message": "hi"}}}'
        ),
    }
    return _ok(payload.trace_id, data=data)


_SCRUB_KEY_MARKERS = ("key", "token", "secret", "password", "auth", "credential")


def _scrub(value: Any) -> Any:
    """Recursively redact secret-looking keys/values from *value*."""
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if any(m in k.lower() for m in _SCRUB_KEY_MARKERS) else _scrub(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


@app.post("/tools/feedback")
async def feedback(payload: ResearchRequest, request: Request) -> ResearchResponse:
    _require_auth(request)

    fb_type = payload.parameters.get("type", "question")
    message = _scrub(payload.parameters.get("message", ""))
    system_data = _scrub(payload.parameters.get("system_data") or {})
    usecase_data = _scrub(payload.parameters.get("usecase_data") or {})

    queue_id = uuid.uuid4().hex
    logger.info(
        "domain-mcp feedback queued: type=%s queue_id=%s message=%s "
        "system=%s usecase=%s",
        fb_type,
        queue_id,
        message,
        system_data,
        usecase_data,
    )
    data = {
        "handled": False,
        "logged": True,
        "response": None,
        "queue_id": queue_id,
    }
    return _ok(payload.trace_id, data=data)
