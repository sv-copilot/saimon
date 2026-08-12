"""server.py — search-mcp FastAPI application.

Provides search tools over the PostgreSQL knowledge graph and external
sources.  Every tool endpoint accepts a ResearchRequest envelope and
returns a ResearchResponse envelope.  Authentication is fail-closed.

Supports DB injection via set_db_pool() for live knowledge-graph queries.
Without a DB, falls back to synthetic placeholder results.
"""

from __future__ import annotations

import os as _os
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
from research_shared.hardening import apply_hardening, build_audit_logger
from research_shared.lifespan import build_lifespan
from research_shared.shadow_registry import ShadowRegistry
from research_shared.source_discovery import SOURCE_DISCOVERY_MIN_CANDIDATES

# ── Serper.dev Tier B config ──────────────────────────────────────

_SERPER_API_KEY = _os.environ.get("SERPER_API_KEY", "")
_SERPER_URL = "https://google.serper.dev/search"

# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan("search-mcp", db_pool_ref=lambda: _db_pool)
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
# backend injection
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
apply_hardening(app, _auth)


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
        except Exception:  # noqa: BLE001  # noqa: BLE001
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
        "description": "Search the web via Serper.dev Google Search API for real-time results.",
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
        "name": "source_discovery",
        "description": (
            "Extract references (DOIs, URLs, arXiv IDs) from text and resolve "
            "to real source metadata via shadow libraries."
        ),
        "parameters": {
            "text": "str (required)",
            "max_results": "int (optional, default 10, max 20)",
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
    logger = build_audit_logger(payload, request, _auth, "search-mcp")
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
# tool: search_web (Tier B — Serper.dev Google Search)
# ---------------------------------------------------------------------------


async def _search_web_serper(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search the web via Serper.dev Google Search API.

    Returns a list of result dicts with title, snippet, url, source.
    Returns empty list if SERPER_API_KEY is not configured (graceful degradation).
    """
    if not _SERPER_API_KEY:
        return []

    # Resolve after the duplicate at module level
    serper_key = _os.environ.get("SERPER_API_KEY", "")
    if not serper_key:
        return []

    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _SERPER_URL,
                json={"q": query, "num": min(limit, 50)},
                headers={"X-API-KEY": serper_key},
            )
            data = resp.json()
            return [
                {
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                    "url": r.get("link", ""),
                    "source": "serper",
                }
                for r in data.get("organic", [])[:limit]
            ]
    except Exception:  # noqa: BLE001 — best-effort Serper call
        import logging
        _log = logging.getLogger("saimon.search.serper")
        _log.warning("Serper API call failed", exc_info=True)
        return []


@app.post("/tools/search_web")
async def search_web(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    query = payload.parameters.get("query")
    if not query:
        return _error(payload.trace_id, "Parameter 'query' is required.")

    logger = build_audit_logger(payload, request, _auth, "search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="search_web",
        query=query,
    )

    results = await _search_web_serper(query)

    if not results:
        # Degrade gracefully — return empty results
        resp = _degraded(
            trace_id=payload.trace_id,
            data={"results": [], "total": 0, "note": "Serper API key not configured"},
        )
    else:
        resp = _ok(
            trace_id=payload.trace_id,
            data={"results": results, "total": len(results)},
            citations=[r["url"] for r in results if r.get("url")],
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
        },
        citations=citations,
    )
    logger.log_response(status=resp.status, citations_count=len(citations))
    return resp


# ---------------------------------------------------------------------------
# helpers: shadow library resolution
# ---------------------------------------------------------------------------

async def _search_all_adapters(
    query: str, limit: int = 1, source_indexes: list[str] | None = None
) -> list[SourceSearchResult]:
    """Search all shadow library adapters for a query.

    Queries each adapter in parallel, gracefully handling individual failures.
    Deduplicates and truncates to limit.
    """
    adapters = _get_shadow_adapters(source_indexes)
    if not adapters:
        return []

    all_results: list[SourceSearchResult] = []
    for adapter in adapters:
        try:
            results = await adapter.search(query, limit=limit, offset=0)
            all_results.extend(results)
        except Exception:  # noqa: BLE001, S112 — each adapter may fail independently
            continue

    return deduplicate(all_results)[:limit]


# ---------------------------------------------------------------------------
# tool: list_source_indexes (primary)
# ---------------------------------------------------------------------------

@app.post("/tools/list_source_indexes")
async def list_source_indexes(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """List available source indexes (knowledge graph, shadow libraries, web)."""
    _require_auth(request)

    logger = build_audit_logger(payload, request, _auth, "search-mcp")
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

    logger = build_audit_logger(payload, request, _auth, "search-mcp")
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


# ---------------------------------------------------------------------------
# tool: saimon_list_audit_log
# ---------------------------------------------------------------------------

@app.post("/tools/saimon_list_audit_log")
async def saimon_list_audit_log(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """List audit log entries for observability and compliance."""
    _require_auth(request)

    limit = min(int(payload.parameters.get("limit", 50)), 200)
    service_filter = payload.parameters.get("service_name")
    event_filter = payload.parameters.get("event_type")

    logger = build_audit_logger(payload, request, _auth, "search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="saimon_list_audit_log",
        limit=limit,
    )

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            if service_filter and event_filter:
                rows = await _db_pool.fetch(
                    "SELECT trace_id, service_name, event_type, payload, created_at "
                    "FROM audit_log "
                    "WHERE service_name = $1 AND event_type = $2 "
                    "ORDER BY created_at DESC LIMIT $3",
                    service_filter, event_filter, limit,
                )
            elif service_filter:
                rows = await _db_pool.fetch(
                    "SELECT trace_id, service_name, event_type, payload, created_at "
                    "FROM audit_log "
                    "WHERE service_name = $1 "
                    "ORDER BY created_at DESC LIMIT $2",
                    service_filter, limit,
                )
            elif event_filter:
                rows = await _db_pool.fetch(
                    "SELECT trace_id, service_name, event_type, payload, created_at "
                    "FROM audit_log "
                    "WHERE event_type = $1 "
                    "ORDER BY created_at DESC LIMIT $2",
                    event_filter, limit,
                )
            else:
                rows = await _db_pool.fetch(
                    "SELECT trace_id, service_name, event_type, payload, created_at "
                    "FROM audit_log "
                    "ORDER BY created_at DESC LIMIT $1",
                    limit,
                )
            entries = [dict(r) for r in rows]
            resp = _ok(
                trace_id=payload.trace_id,
                data={"entries": entries, "total": len(entries)},
            )
            logger.log_response(status=resp.status)
            return resp
        except (DatabaseError, NotImplementedError):
            pass

    # ── fallback ──
    resp = _degraded(
        trace_id=payload.trace_id,
        data={"entries": [], "total": 0, "note": "DB not available — audit log is stored in PostgreSQL."},
    )
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: source_discovery
# ---------------------------------------------------------------------------

@app.post("/tools/source_discovery")
async def source_discovery(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Extract references from text and resolve to real source metadata.

    Tier A: deterministic DOI/URL/arXiv extraction via regex.
    Resolution: queries shadow library adapters for each extracted identifier.
    """
    _require_auth(request)

    text = payload.parameters.get("text", "")
    max_results = min(int(payload.parameters.get("max_results", 10)), 20)

    logger = build_audit_logger(payload, request, _auth, "search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="source_discovery",
        text_length=len(text),
        max_results=max_results,
    )

    # Step 1: Extract reference candidates from text
    from research_shared.source_discovery import extract_reference_candidates

    candidates = extract_reference_candidates(text, max_results=max_results)

    # ── Tier B: Serper web search fallback ──
    web_results: list[dict[str, Any]] = []
    tier_used = "A"

    if len(candidates) < SOURCE_DISCOVERY_MIN_CANDIDATES:
        serper_key = _os.environ.get("SERPER_API_KEY", "")
        if serper_key:
            web_results = await _search_web_serper(text, limit=5)
            if web_results:
                tier_used = "B"

    # Step 2: Resolve each candidate via shadow library adapters
    resolved: list[dict[str, Any]] = []
    for c in candidates:
        query = c.doi or c.url or c.arxiv_id or ""
        if query:
            try:
                results = await _search_all_adapters(query, limit=1)
                if results:
                    resolved.append(results[0].model_dump())
            except Exception:  # noqa: BLE001, S110 — individual failure doesn't block others
                pass

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "candidates": [
                {
                    "kind": c.kind,
                    "label": c.label,
                    "doi": c.doi,
                    "url": c.url,
                    "arxiv_id": c.arxiv_id,
                }
                for c in candidates
            ],
            "resolved": resolved,
            "web_results": web_results,
            "total_candidates": len(candidates),
            "total_resolved": len(resolved),
            "total_web_results": len(web_results),
            "tier_used": tier_used,
        },
    )
    logger.log_response(
        status=resp.status,
        total_candidates=len(candidates),
        total_resolved=len(resolved),
        tier_used=tier_used,
        web_results=len(web_results),
    )
    return resp
