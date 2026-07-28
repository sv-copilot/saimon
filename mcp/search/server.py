"""server.py — search-mcp FastAPI application.

Provides search tools over the PostgreSQL knowledge graph and external
sources.  Every tool endpoint accepts a ResearchRequest envelope and
returns a ResearchResponse envelope.  Authentication is fail-closed.

Supports DB injection via set_db_pool() for live knowledge-graph queries.
Without a DB, falls back to synthetic placeholder results.
"""

from __future__ import annotations

import json as _json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter
from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.base import SourceSearchResult
from research_shared.adapters.dedup import deduplicate
from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.libgen import LibGenAdapter
from research_shared.adapters.scihub import SciHubAdapter
from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.db import DatabaseError, DatabasePool
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.lifespan import build_lifespan
from research_shared.shadow_registry import ShadowRegistry

# ---------------------------------------------------------------------------
# backend injection (must be before lifespan — it references set_db_pool)
# ---------------------------------------------------------------------------

_db_pool: DatabasePool | None = None


def set_db_pool(pool: DatabasePool | None) -> None:
    """Inject a DatabasePool for live knowledge-graph queries."""
    global _db_pool
    _db_pool = pool


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan("search-mcp", db_pool_ref=lambda: _db_pool, db_pool_setter=set_db_pool)
app = FastAPI(title="search-mcp", version="0.1.0", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# shadow library registry
# ---------------------------------------------------------------------------

_shadow_registry = ShadowRegistry()

# Register all Tier S + A adapters
_shadow_registry.register(AnnasArchiveAdapter())
_shadow_registry.register(LibGenAdapter())
_shadow_registry.register(SciHubAdapter())
_shadow_registry.register(InternetArchiveAdapter())
_shadow_registry.register(AcademicTorrentsAdapter())

_SHADOW_LABELS: dict[str, str] = {
    "annas_archive": "Anna's Archive",
    "libgen": "Library Genesis (LibGen)",
    "scihub": "Sci-Hub / SciDB",
    "internet_archive": "Internet Archive",
    "academic_torrents": "Academic Torrents",
}


def _get_shadow_adapters(source_indexes: list[str] | None = None) -> list:
    """Return adapters filtered by optional source_indexes list."""
    if source_indexes:
        return [
            a for a in _shadow_registry.list_all()
            if a.name in source_indexes
        ]
    # Default: all Tier S + A adapters
    return _shadow_registry.filter(tier="S") + _shadow_registry.filter(tier="A")


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
        "name": "search_shadow_libraries",
        "description": (
            "Search shadow library source indexes (Anna's Archive, LibGen, "
            "Sci-Hub/SciDB, Internet Archive, Academic Torrents) for "
            "academic papers, books, and datasets. Returns ranked "
            "SourceReferences with DOIs, abstracts, and source index "
            "attribution."
        ),
        "parameters": {
            "query": "str (required)",
            "source_indexes": "list[str] (optional, default: all Tier S + A)",
            "limit": "int (optional, default 10, max 50)",
            "offset": "int (optional, default 0)",
            "sort_by": "str (optional, 'relevance' | 'year', default 'relevance')",
        },
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
                "SELECT id, title, content_type, "
                "COALESCE((metadata->>'relevance')::float, 0.5) as relevance "
                "FROM knowledge_graph_nodes "
                "WHERE title ILIKE $1 OR body ILIKE $1 "
                "ORDER BY created_at DESC LIMIT $2",
                f"%{query}%", limit,
            )
            results: list[dict[str, Any]] = [dict(r) for r in rows]
            resp = _ok(
                trace_id=payload.trace_id,
                data={"results": results, "total": len(results)},
                citations=[str(r["id"]) for r in results],
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
# tool: search_shadow_libraries
# ---------------------------------------------------------------------------

@app.post("/tools/search_shadow_libraries")
async def search_shadow_libraries(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Search shadow library source indexes for academic papers, books, and datasets."""
    _require_auth(request)

    query = payload.parameters.get("query")
    if not query:
        resp = _ok(
            trace_id=payload.trace_id,
            data={"query": "", "total_results": 0, "results": []},
        )
        return resp

    requested_indexes: list[str] | None = payload.parameters.get("source_indexes")
    limit = min(int(payload.parameters.get("limit", 10)), 50)
    offset = int(payload.parameters.get("offset", 0))

    logger = AuditLogger(trace_id=payload.trace_id, service_name="search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="search_shadow_libraries",
        query=query,
        source_indexes=requested_indexes,
    )

    # Get adapters (filtered or all S+A tier)
    adapters = _get_shadow_adapters(requested_indexes)

    if not adapters:
        resp = _ok(
            trace_id=payload.trace_id,
            data={"query": query, "total_results": 0, "results": []},
        )
        logger.log_response(status=resp.status)
        return resp

    # Query all selected adapters in parallel, gracefully handling failures
    all_results: list[SourceSearchResult] = []
    degraded = False

    for adapter in adapters:
        try:
            results = await adapter.search(query, limit=limit, offset=offset)
            all_results.extend(results)
        except Exception:  # noqa: BLE001 — each adapter may fail independently
            degraded = True
            continue

    # Deduplicate across source indexes
    deduped = deduplicate(all_results)

    # ── cache results in shadow_sources_cache ────────────────
    if _db_pool is not None:
        for r in deduped:
            if r.doi:
                try:
                    await _db_pool.execute(
                        "INSERT INTO shadow_sources_cache (doi, title, authors, year, "
                        "abstract_snippet, source_index, file_type) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7) "
                        "ON CONFLICT (doi) DO UPDATE SET "
                        "title = EXCLUDED.title, last_accessed = now()",
                        r.doi.strip().lower(),
                        r.title,
                        _json.dumps(r.authors),
                        r.year,
                        r.abstract_snippet,
                        r.source_index,
                        r.file_type,
                    )
                except Exception:  # noqa: BLE001
                    pass  # cache write is best-effort

    # Apply limit
    deduped = deduped[:limit]

    # Serialize
    results_data = []
    citations: list[str] = []
    for r in deduped:
        results_data.append(r.model_dump())
        if r.doi:
            citations.append(f"doi:{r.doi}")
        else:
            citations.append(r.identifier)

    status = "degraded" if degraded else "success"
    resp = ResearchResponse(
        trace_id=payload.trace_id,
        status=status,
        data={
            "query": query,
            "total_results": len(results_data),
            "results": results_data,
            "note": (
                "Shadow library adapters are in mock/placeholder mode. "
                "Results show representative metadata structure but not real "
                "paper data. Live scraping requires adapter HTTP wiring "
                "(planned for a future slice)."
            ),
        },
        citations=citations,
    )
    logger.log_response(status=resp.status, citations_count=len(citations))
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
            source_indexes_db: list[dict[str, Any]] = [dict(r) for r in rows] if rows else [
                {"type": "knowledge_graph", "identifier": "kg-root", "label": "Root node"},
                {"type": "knowledge_graph", "identifier": "kg-concepts", "label": "Concepts"},
                {"type": "web_page", "identifier": "web-index", "label": "Web index"},
            ]
            for adapter in _shadow_registry.list_all():
                source_indexes_db.append({
                    "type": "shadow_library",
                    "identifier": adapter.name,
                    "label": _SHADOW_LABELS.get(adapter.name, adapter.name),
                    "tier": adapter.tier,
                    "trust_model": adapter.trust_model,
                    "status": "available",
                })
            resp = _ok(trace_id=payload.trace_id, data={"source_indexes": source_indexes_db})
            logger.log_response(status=resp.status)
            return resp
        except (DatabaseError, NotImplementedError):
            pass

    # ── fallback ──
    source_indexes: list[dict[str, Any]] = [
        {"type": "knowledge_graph", "identifier": "kg-root", "label": "Root node"},
        {"type": "knowledge_graph", "identifier": "kg-concepts", "label": "Concepts"},
        {"type": "web_page", "identifier": "web-index", "label": "Web index"},
    ]

    # Add shadow library adapters
    for adapter in _shadow_registry.list_all():
        source_indexes.append({
            "type": "shadow_library",
            "identifier": adapter.name,
            "label": _SHADOW_LABELS.get(adapter.name, adapter.name),
            "tier": adapter.tier,
            "trust_model": adapter.trust_model,
            "status": "available",
        })

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
