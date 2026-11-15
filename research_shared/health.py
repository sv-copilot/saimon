"""health.py — shared health aggregation utilities for saimon MCPs.

Provides a reusable health checker that can probe all registered MCP
services in parallel and aggregate their /health responses.
"""

from __future__ import annotations

import asyncio as _asyncio
import logging as _logging
import os as _os
from typing import Any

import httpx as _httpx

_log = _logging.getLogger("saimon.health")


# ---------------------------------------------------------------------------
# service registry
# ---------------------------------------------------------------------------

_DEFAULT_SERVICE_URLS: dict[str, str] = {
    "search": "http://search:8001",
    "generate": "http://localhost:8002",
    "export": "http://export:8003",
    "evaluate": "http://evaluate:8004",
    "verify": "http://verify:8005",
    "explore": "http://explore:8006",
    "crew": "http://crew-mcp:8009",
}


def _resolve_service_urls() -> dict[str, str]:
    """Resolve service URLs from environment or defaults."""
    urls: dict[str, str] = {}
    for name, default in _DEFAULT_SERVICE_URLS.items():
        env_key = f"SAIMON_{name.upper()}_URL"
        urls[name] = _os.environ.get(env_key, default)
    return urls


# ---------------------------------------------------------------------------
# health aggregation
# ---------------------------------------------------------------------------


async def check_all_services(
    timeout: float = 5.0,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Probe all registered MCP /health endpoints in parallel.

    Args:
        timeout: Per-service HTTP timeout in seconds.
        api_key: Optional API key for services that require auth on /health.

    Returns:
        {
            "status": "ok" | "degraded" | "down",
            "services": {name: {"status": ..., "latency_ms": ..., ...}},
            "summary": "N/M services healthy",
        }
    """
    urls = _resolve_service_urls()

    async def _probe(name: str, base_url: str) -> dict[str, Any]:
        import time as _time

        start = _time.monotonic()
        try:
            headers = {}
            if api_key:
                headers["X-Saimon-API-Key"] = api_key
            async with _httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base_url}/health", headers=headers)
                data = resp.json() if resp.headers.get("content-type", "").startswith(
                    "application/json"
                ) else {}
                elapsed = (_time.monotonic() - start) * 1000
                return {
                    "name": name,
                    "status": data.get("status", "ok" if resp.status_code == 200 else "degraded"),
                    "checks": data.get("checks", {}),
                    "latency_ms": round(elapsed, 1),
                    "http_status": resp.status_code,
                }
        except _httpx.TimeoutException:
            elapsed = (_time.monotonic() - start) * 1000
            _log.warning("Health check timeout for %s (%s)", name, base_url)
            return {"name": name, "status": "unreachable", "error": "timeout", "latency_ms": round(elapsed, 1)}
        except Exception as exc:  # noqa: BLE001
            elapsed = (_time.monotonic() - start) * 1000
            _log.warning("Health check failed for %s (%s): %s", name, base_url, exc)
            return {"name": name, "status": "unreachable", "error": str(exc), "latency_ms": round(elapsed, 1)}

    tasks = [_probe(name, url) for name, url in urls.items()]
    results = await _asyncio.gather(*tasks)

    healthy = sum(1 for r in results if r["status"] == "ok")
    total = len(results)

    if healthy == total:
        overall = "ok"
    elif healthy > 0:
        overall = "degraded"
    else:
        overall = "down"

    services = {r.pop("name"): r for r in results}

    return {
        "status": overall,
        "service": "health-aggregator",
        "services": services,
        "summary": f"{healthy}/{total} services healthy",
    }



# ---------------------------------------------------------------------------
# status derivation
# ---------------------------------------------------------------------------

# A check value in one of these states means the dependency is not usable. Status is derived
# from the checks rather than hardcoded, because a body that says ok while a check says
# unavailable is a green light over a broken dependency.
_FAILURE_STATES = frozenset(
    {"unavailable", "error", "failed", "failure", "down", "disconnected", "timeout", "not connected"}
)


def _check_failed(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in _FAILURE_STATES
    if isinstance(value, dict):
        return any(_check_failed(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_check_failed(v) for v in value)
    return False


def derive_status(checks: dict[str, Any]) -> str:
    """Return "degraded" when any check reports a failed dependency, else "ok".

    Counts, booleans and free text carry no failure vocabulary and are ignored, which keeps
    the rule narrow enough to trust.
    """
    return "degraded" if any(_check_failed(v) for v in checks.values()) else "ok"


def finalize_health(body: dict[str, Any]) -> dict[str, Any]:
    """Set body["status"] from body["checks"] and return the body.

    Every service /health endpoint returns through this, so the status field cannot drift
    from the checks beside it.
    """
    body["status"] = derive_status(body.get("checks") or {})
    return body
