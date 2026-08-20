"""server.py — crew-mcp FastAPI application (SAIMON-CREW-SERVICE-1).

The 9th saimon MCP service: hosts CrewAI crews behind the standard
research_shared envelope/auth/hardening/lifespan pattern. CrewAI is imported
lazily (see mcp.crew.llm) so the other eight services stay CrewAI-free.

Tool contract (v1):
- ``crew.research@v1`` — research-analyst crew answering a topic with grounded
  saimon evidence (search KG / verify / explore). Route ``saimon.research``
  (reasoning, pro). Implemented in SAIMON-CREW-RESEARCH-1 (#95).
- ``crew.extract_claims@v1`` — falsifiable, time-anchored claim extraction.
  Route ``saimon.extract_claims`` (mechanical, flash). Implemented in
  SAIMON-CREW-CLAIM-EXTRACT-1 (#96).
"""

from __future__ import annotations

import logging as _logging
import os as _os
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.hardening import apply_hardening
from research_shared.lifespan import build_lifespan

# ---------------------------------------------------------------------------
# backend injection (must be before lifespan)
# ---------------------------------------------------------------------------

_db_pool: Any | None = None
_llm_client: Any | None = None


def set_db_pool(pool: Any | None) -> None:
    """Inject a DatabasePool for observations persistence."""
    global _db_pool
    _db_pool = pool


def set_llm_client(client: Any | None) -> None:
    """Inject an LLMClient (non-crew endpoints only)."""
    global _llm_client
    _llm_client = client


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan(
    "crew-mcp",
    db_pool_ref=lambda: _db_pool,
    db_pool_setter=set_db_pool,
    llm_client_ref=lambda: _llm_client,
    llm_client_setter=set_llm_client,
)
app = FastAPI(title="crew-mcp", version="0.1.0", lifespan=_lifespan)

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)
apply_hardening(app, _auth)


def _require_auth(request: Request) -> None:
    if _auth.has_api_key:
        key = _auth.extract_from_headers(dict(request.headers))
        try:
            _auth.validate(key)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


# ---------------------------------------------------------------------------
# tool contract
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "crew.research@v1",
        "description": (
            "Research-analyst CrewAI crew answering a topic with grounded saimon "
            "evidence (search KG / verify / explore). Never invents content a "
            "tool did not return."
        ),
        "parameters": {"topic": "str", "max_messages": "int (optional)"},
    },
    {
        "name": "crew.extract_claims@v1",
        "description": (
            "Extract falsifiable, time-anchored claim candidates from source text, "
            "excluding bylines/headings/ToC, filtered by a quality gate."
        ),
        "parameters": {"text": "str"},
    },
]


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    db_ok = False
    if _db_pool is not None:
        try:
            await _db_pool.fetch("SELECT 1")
            db_ok = True
        except Exception:
            _logging.getLogger("saimon.crew").debug(
                "crew-mcp health: DB not reachable", exc_info=True
            )
    return {
        "status": "ok",
        "service": "crew-mcp",
        "checks": {"database": "connected" if db_ok else "unavailable"},
    }


@app.get("/health/aggregate")
async def health_aggregate() -> dict[str, Any]:
    """Aggregate health across all saimon MCP services."""
    from research_shared.health import check_all_services

    api_key = _os.environ.get("SAIMON_API_KEY")
    return await check_all_services(api_key=api_key)


@app.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    _require_auth(request)
    return {"tools": _TOOLS}
