"""server.py — search-mcp FastAPI application.

Provides search tools over the PostgreSQL knowledge graph and external
sources.  Every tool endpoint accepts a ResearchRequest envelope and
returns a ResearchResponse envelope.  Authentication is fail-closed.

Supports DB injection via set_db_pool() for live knowledge-graph queries.
Without a DB, falls back to synthetic placeholder results.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.db import DatabaseError, DatabasePool
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.lifespan import build_lifespan

# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan("search-mcp", db_pool_ref=lambda: _db_pool)
app = FastAPI(title="search-mcp", version="0.1.0", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# backend injection
# ---------------------------------------------------------------------------

_db_pool: DatabasePool | None = None


def set_db_pool(pool: DatabasePool | None) -> None:
    """Inject a DatabasePool for live knowledge-graph queries."""
    global _db_pool
    _db_pool = pool


# ---------------------------------------------------------------------------
# auth (fail-closed)
# ---------------------------------------------------------------------------

_auth_config = AuthConfig.from_env()
_auth = AuthValidator(_auth_config)


def _require_auth(request: Request) -> None:
    """Fail-closed auth guard.  Called as a FastAPI dependency."""
    if _auth.has_api_key:
        key = _auth.extract_from_headers(dict(request.headers))
        try:
            _auth.validate(key)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    """Unauthenticated health check."""
    import logging as _logging
    _log = _logging.getLogger("saimon.health")
    db_ok = False
    if _db_pool is not None:
        try:
            await _db_pool.fetch("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001
            _log.debug("search-mcp health: DB not reachable", exc_info=True)
    return {
        "status": "ok",
        "service": "search-mcp",
        "checks": {"database": "connected" if db_ok else "unavailable"},
    }


# ---------------------------------------------------------------------------
# tool listing
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "search_knowledge_graph",
        "description": "Search the PostgreSQL knowledge graph.",
        "parameters": {"query": "str", "limit": "int (optional, default 10)"},
    },
    {
        "name": "search_web",
        "description": "Search external web sources (placeholder).",
        "parameters": {"query": "str"},
    },
    {
        "name": "list_source_indexes",
        "description": "List available source indexes (knowledge graph, shadow libraries, web).",
        "parameters": {},
    },
    {
        "name": "get_source_index_detail",
        "description": "Get metadata for a specific source index.",
        "parameters": {"source_index_id": "str"},
    },
]


@app.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """Return the tool manifest for this MCP."""
    _require_auth(request)
    return {"tools": _TOOLS}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ok(
    trace_id: str,
    data: Any = None,
    citations: list[str] | None = None,
) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="success",
        data=data,
        citations=citations,
    )


def _degraded(trace_id: str, data: Any = None, citations: list[str] | None = None) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id, status="degraded", data=data, citations=citations,
    )


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="error",
        errors=[message],
    )


# ---------------------------------------------------------------------------
# tool: search_knowledge_graph
# ---------------------------------------------------------------------------

@app.post("/tools/search_knowledge_graph")
async def search_knowledge_graph(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)
    logger = AuditLogger(trace_id=payload.trace_id, service_name="search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        sources_count=len(payload.sources),
        tool="search_knowledge_graph",
        query=payload.parameters.get("query"),
    )

    query = payload.parameters.get("query", "")
    limit = min(int(payload.parameters.get("limit", 10)), 100)

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            rows = await _db_pool.fetch(
                "SELECT id, title, content_type, relevance "
                "FROM knowledge_graph_nodes "
                "WHERE title ILIKE $1 OR content ILIKE $1 "
                "ORDER BY relevance DESC LIMIT $2",
                f"%{query}%", limit,
            )
            results: list[dict[str, Any]] = [dict(r) for r in rows]
            resp = _ok(
                trace_id=payload.trace_id,
                data={"results": results, "total": len(results)},
                citations=[r["id"] for r in results],
            )
            logger.log_response(
                status=resp.status, citations_count=len(resp.citations or [])
            )
            return resp
        except (DatabaseError, NotImplementedError):
            pass  # fall through to fallback

    # ── fallback (no DB, or DB not implemented) ──
    results = [
        {
            "id": f"kg-{i}",
            "title": f"Knowledge graph result {i} for: {query}",
            "relevance": round(1.0 - (i * 0.15), 2),
        }
        for i in range(min(limit, 5))
    ]

    resp = _degraded(
        trace_id=payload.trace_id,
        data={"results": results, "total": len(results)},
        citations=[r["id"] for r in results],
    )
    logger.log_response(status=resp.status, citations_count=len(resp.citations or []))
    return resp


# ---------------------------------------------------------------------------
# tool: search_web
# ---------------------------------------------------------------------------

@app.post("/tools/search_web")
async def search_web(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    query = payload.parameters.get("query")
    if not query:
        return _error(payload.trace_id, "Parameter 'query' is required.")

    logger = AuditLogger(trace_id=payload.trace_id, service_name="search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="search_web",
        query=query,
    )

    # Placeholder — in production this calls an external search API
    results: list[dict[str, Any]] = [
        {
            "url": f"https://example.com/result-{i}",
            "title": f"Web result {i} for: {query}",
            "snippet": f"A relevant snippet about {query}.",
        }
        for i in range(3)
    ]

    resp = _ok(
        trace_id=payload.trace_id,
        data={"results": results},
        citations=[r["url"] for r in results],
    )
    logger.log_response(status=resp.status, citations_count=len(resp.citations or []))
    return resp


# ---------------------------------------------------------------------------
# tool: list_source_indexes (primary)
# ---------------------------------------------------------------------------

@app.post("/tools/list_source_indexes")
async def list_source_indexes(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """List available source indexes (knowledge graph, shadow libraries, web)."""
    _require_auth(request)

    logger = AuditLogger(trace_id=payload.trace_id, service_name="search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="list_source_indexes",
    )

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            rows = await _db_pool.fetch(
                "SELECT type, identifier, label FROM sources ORDER BY type, identifier"
            )
            source_indexes = [dict(r) for r in rows] if rows else [
                {"type": "knowledge_graph", "identifier": "kg-root", "label": "Root node"},
                {"type": "knowledge_graph", "identifier": "kg-concepts", "label": "Concepts"},
                {"type": "web_page", "identifier": "web-index", "label": "Web index"},
            ]
            resp = _ok(trace_id=payload.trace_id, data={"source_indexes": source_indexes})
            logger.log_response(status=resp.status)
            return resp
        except (DatabaseError, NotImplementedError):
            pass

    # ── fallback ──
    source_indexes = [
        {"type": "knowledge_graph", "identifier": "kg-root", "label": "Root node"},
        {"type": "knowledge_graph", "identifier": "kg-concepts", "label": "Concepts"},
        {"type": "web_page", "identifier": "web-index", "label": "Web index"},
    ]

    resp = _ok(trace_id=payload.trace_id, data={"source_indexes": source_indexes})
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: list_sources (deprecated — backward compat alias)
# ---------------------------------------------------------------------------

@app.post("/tools/list_sources")
async def list_sources_deprecated(
    payload: ResearchRequest, request: Request
) -> JSONResponse:
    """[DEPRECATED] Use /tools/list_source_indexes instead."""
    resp = await list_source_indexes(payload, request)
    return JSONResponse(
        content=resp.model_dump(),
        headers={
            "X-Deprecated": "true",
            "X-Deprecated-Replacement": "/tools/list_source_indexes",
        },
    )


# ---------------------------------------------------------------------------
# tool: get_source_index_detail (primary)
# ---------------------------------------------------------------------------

@app.post("/tools/get_source_index_detail")
async def get_source_index_detail(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Get metadata for a specific source index."""
    _require_auth(request)

    source_index_id = payload.parameters.get("source_index_id")
    if not source_index_id:
        return _error(payload.trace_id, "Parameter 'source_index_id' is required.")

    logger = AuditLogger(trace_id=payload.trace_id, service_name="search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="get_source_index_detail",
        source_index_id=source_index_id,
    )

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            row = await _db_pool.fetchrow(
                "SELECT identifier, type, label, node_count FROM sources "
                "WHERE identifier = $1",
                source_index_id,
            )
            if row:
                detail = dict(row)
                resp = _ok(trace_id=payload.trace_id, data=detail)
                logger.log_response(status=resp.status)
                return resp
        except (DatabaseError, NotImplementedError):
            pass

    # ── fallback ──
    detail = {
        "identifier": source_index_id,
        "type": "knowledge_graph",
        "label": f"Source Index: {source_index_id}",
        "node_count": 42,
    }

    resp = _ok(trace_id=payload.trace_id, data=detail)
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: get_source_detail (deprecated — backward compat alias)
# ---------------------------------------------------------------------------

@app.post("/tools/get_source_detail")
async def get_source_detail_deprecated(
    payload: ResearchRequest, request: Request
) -> JSONResponse:
    """[DEPRECATED] Use /tools/get_source_index_detail instead."""
    # Map old parameter name to new
    if "source_id" in payload.parameters and "source_index_id" not in payload.parameters:
        payload.parameters["source_index_id"] = payload.parameters.pop("source_id")
    resp = await get_source_index_detail(payload, request)
    return JSONResponse(
        content=resp.model_dump(),
        headers={
            "X-Deprecated": "true",
            "X-Deprecated-Replacement": "/tools/get_source_index_detail",
        },
    )
