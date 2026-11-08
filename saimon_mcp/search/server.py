"""server.py — search-mcp FastAPI application.

Provides search tools over the PostgreSQL knowledge graph and external
sources.  Every tool endpoint accepts a ResearchRequest envelope and
returns a ResearchResponse envelope.  Authentication is fail-closed.

Supports DB injection via set_db_pool() for live knowledge-graph queries.
Without a DB, falls back to synthetic placeholder results.
"""

from __future__ import annotations

import asyncio
import os as _os
from datetime import UTC
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter
from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.base import SourceSearchResult
from research_shared.adapters.dedup import deduplicate
from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.libgen import LibGenAdapter
from research_shared.adapters.ranking import rank_shadow_results
from research_shared.adapters.scihub import SciHubAdapter
from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.db import DatabaseError, DatabasePool
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.hardening import apply_hardening, build_audit_logger
from research_shared.lifespan import build_lifespan
from research_shared.rerank import RerankConfig, reformulate_query, rerank
from research_shared.shadow_registry import ShadowRegistry
from research_shared.source_discovery import SOURCE_DISCOVERY_MIN_CANDIDATES

# ── Serper.dev Tier B config ──────────────────────────────────────

_SERPER_API_KEY = _os.environ.get("SERPER_API_KEY", "")
_SERPER_URL = "https://google.serper.dev/search"

# ---------------------------------------------------------------------------
# backend injection
# ---------------------------------------------------------------------------

_db_pool: DatabasePool | None = None


def set_db_pool(pool: DatabasePool | None) -> None:
    """Inject a DatabasePool for live knowledge-graph queries."""
    global _db_pool
    _db_pool = pool


# ---------------------------------------------------------------------------
# retrieval rerank configuration (SAIMON-RETRIEVAL-RERANK-1)
# ---------------------------------------------------------------------------

_rerank_config = RerankConfig.from_env()


def _rerank_embed_fn() -> Any:
    """Return a fail-closed embedding callable for the reranker.

    Returns a callable that maps text -> vector (or None).  Uses the same local
    embedding backend as the vector search path, so cosine similarity can be
    computed for keyword-only passages that have no precomputed embedding.
    """
    from research_shared.embedding import EmbeddingConfig, embed_local

    cfg = EmbeddingConfig.from_env()

    def embed(text: str) -> list[float] | None:
        return embed_local(text, cfg.model, cfg.dimensions)

    return embed


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

# Default source indexes queried by search_shadow_libraries.  Academic Torrents
# is excluded because its API 404s on every query (SAIMON-SEARCH-RELIABILITY-1).
_DEFAULT_SHADOW_INDEXES = frozenset(
    {"annas_archive", "libgen", "scihub", "internet_archive"}
)


def _get_shadow_adapters(source_indexes: list[str] | None = None) -> list:
    """Return adapters filtered by optional source_indexes list."""
    if source_indexes:
        return [
            a for a in _shadow_registry.list_all()
            if a.name in source_indexes
        ]
    # Default: Tier S book/paper sources plus Internet Archive.  Academic
    # Torrents is excluded because its API 404s on every query (burning a 15s
    # timeout per query with no results) — SAIMON-SEARCH-RELIABILITY-1 (#201).
    return [
        a for a in _shadow_registry.list_all()
        if a.name in _DEFAULT_SHADOW_INDEXES
    ]


def _shadow_index_entry(adapter: Any) -> dict[str, Any]:
    """Serialize a shadow registry adapter for list_source_indexes.

    Disabled adapters (e.g. Academic Torrents, whose search endpoint was
    removed upstream) are surfaced with ``status: "disabled"`` and a
    ``disabled_reason`` instead of the default ``"available"``.
    """
    disabled = bool(getattr(adapter, "disabled", False))
    entry: dict[str, Any] = {
        "type": "shadow_library",
        "identifier": adapter.name,
        "label": _SHADOW_LABELS.get(adapter.name, adapter.name),
        "tier": adapter.tier,
        "trust_model": adapter.trust_model,
        "status": "disabled" if disabled else "available",
    }
    if disabled:
        entry["disabled_reason"] = getattr(
            adapter, "disabled_reason", "source index disabled"
        )
    return entry


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
    {
        "name": "download_fulltext",
        "description": (
            "Download the full text of a discovered document (DOI or source "
            "result) to object storage and ingest it into the knowledge graph "
            "as fulltext_document + fulltext_chunk nodes. Consent-gated by "
            "FULLTEXT_DOWNLOAD_CONSENT; deduplicated on DOI."
        ),
        "parameters": {
            "doi": "str (optional — canonical DOI)",
            "source": "dict (optional — source result from search_shadow_libraries)",
            "source_indexes": "list[str] (optional — restrict source indexes)",
            "fetch_only": "bool (optional — download + cache, skip RAG ingestion)",
        },
    },
    {
        "name": "saimon_list_audit_log",
        "description": (
            "Read-only listing of audit_log entries for observability and KPI "
            "measurement. Returns entries with service_name, event_type, "
            "trace_id, and payload (incl. citations_count and verify verdicts). "
            "Filterable by service_name, event_type, payload key, and time range."
        ),
        "parameters": {
            "service_name": "str (optional)",
            "event_type": "str (optional)",
            "payload_key": "str (optional — entries whose payload contains this key)",
            "created_after": "str (optional — ISO timestamp, inclusive lower bound)",
            "created_before": "str (optional — ISO timestamp, inclusive upper bound)",
            "limit": "int (optional, default 50, max 200)",
        },
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


async def _vector_search(
    query: str, limit: int, user_id: str | None
) -> list[dict[str, Any]] | None:
    """pgvector cosine-similarity search over knowledge graph embeddings.

    Returns None when the query cannot be embedded (no local model) or no DB
    pool is available, so callers fall back to keyword search.
    """
    from research_shared.embedding import EmbeddingConfig, embed_local

    cfg = EmbeddingConfig.from_env()
    vector = embed_local(query, cfg.model, cfg.dimensions, cfg.model_path or None)
    if vector is None or _db_pool is None:
        return None

    select = (
        "SELECT id, title, body, content_type, "
        "COALESCE((metadata->>'relevance')::float, 0.5) as relevance, "
        "1 - (embedding <=> $1) as similarity "
        "FROM knowledge_graph_nodes "
        "WHERE embedding IS NOT NULL"
    )
    if user_id:
        rows = await _db_pool.fetch(
            select + " AND (user_id = $2 OR user_id IS NULL) "
            "ORDER BY embedding <=> $1 LIMIT $3",
            vector,
            user_id,
            limit,
        )
    else:
        rows = await _db_pool.fetch(
            select + " AND user_id IS NULL ORDER BY embedding <=> $1 LIMIT $2",
            vector,
            limit,
        )
    return [dict(row) for row in rows]


async def _keyword_search(
    query: str, limit: int, user_id: str | None
) -> list[dict[str, Any]]:
    """Lexical search over title/body (parity with ``explore_content``).

    Splits multi-word queries into per-word ILIKE conditions so
    "Sprocket bartender" matches "Sprocket is a bartender".  Returns [] when
    no DB pool is available.
    """
    if _db_pool is None:
        return []

    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        words = [query] if query else [""]

    # Build user-scoping clause
    # Default (no user_id): shared-only (user_id IS NULL)
    # With user_id: user's content + shared (user_id = $n OR user_id IS NULL)
    user_clause: str
    user_params: list[Any] = []
    if user_id:
        user_clause = " AND (user_id = $1 OR user_id IS NULL)"
        user_params = [user_id]
    else:
        user_clause = " AND user_id IS NULL"
        user_params = []

    if len(words) == 1:
        params = user_params + [f"%{words[0]}%", limit]
        offset = len(user_params)
        rows = await _db_pool.fetch(
            "SELECT id, title, body, content_type, "
            "COALESCE((metadata->>'relevance')::float, 0.5) as relevance "
            "FROM knowledge_graph_nodes "
            "WHERE (title ILIKE $" + str(offset + 1) + " OR body ILIKE $" + str(offset + 1) + ")"
            + user_clause + " "
            "ORDER BY created_at DESC LIMIT $" + str(offset + 2),
            *params,
        )
    else:
        # Build per-word conditions: (title ILIKE $n OR body ILIKE $n) AND ...
        conditions = []
        params = list(user_params)
        for w in words:
            params.append(f"%{w}%")
            conditions.append(f"(title ILIKE ${len(params)} OR body ILIKE ${len(params)})")
        params.append(limit)
        sql = (
            "SELECT id, title, body, content_type, "
            "COALESCE((metadata->>'relevance')::float, 0.5) as relevance "
            "FROM knowledge_graph_nodes "
            "WHERE " + " AND ".join(conditions) + user_clause + " "
            "ORDER BY created_at DESC LIMIT $" + str(len(params))
        )
        rows = await _db_pool.fetch(sql, *params)
    return [dict(row) for row in rows]


def _merge_results(
    vector: list[dict[str, Any]],
    keyword: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Merge vector + keyword results, deduplicating by id.

    Vector (semantic) results lead; keyword (lexical) results fill the
    remainder, catching no-embedding nodes the vector path cannot see.
    """
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in vector:
        rid = str(row.get("id"))
        if rid not in seen:
            merged.append(row)
            seen.add(rid)
            if len(merged) >= limit:
                return merged
    for row in keyword:
        rid = str(row.get("id"))
        if rid not in seen:
            merged.append(row)
            seen.add(rid)
            if len(merged) >= limit:
                return merged
    return merged


async def _search_candidates(
    query: str, limit: int, user_id: str | None
) -> list[dict[str, Any]]:
    """Run vector + keyword retrieval and merge into a broad candidate pool."""
    vector_results = await _vector_search(query, limit, user_id) or []
    keyword_results = await _keyword_search(query, limit, user_id)
    return _merge_results(vector_results, keyword_results, limit)


async def _retrieve_and_rerank(
    query: str,
    limit: int,
    user_id: str | None,
    logger: Any,
) -> dict[str, Any]:
    """Retrieve candidates, rerank them, and apply the fail-safe no-answer gate.

    Returns the response ``data`` dict: ``results`` (ranked top-K), ``total``,
    ``no_strong_evidence`` and ``requery_count``.  Logs the ``retrieval.rerank``
    audit event with candidate/kept/top-score/fail-safe metrics.
    """
    config = _rerank_config
    embed_fn = _rerank_embed_fn()

    # Retrieve a broader candidate pool than the final top-K so the reranker
    # can narrow by relevance rather than by adapter order.
    candidate_limit = max(limit * 2, config.top_k)

    candidates = await _search_candidates(query, candidate_limit, user_id)
    outcome = rerank(query, candidates, config, embed_fn=embed_fn, top_k=limit)

    requery_count = 0
    reformulated = query
    if outcome.fail_safe_fired and config.max_requery > 0:
        requery_count = 1
        reformulated = reformulate_query(query)
        requery_candidates = await _search_candidates(
            reformulated, candidate_limit, user_id
        )
        outcome = rerank(
            reformulated, requery_candidates, config, embed_fn=embed_fn, top_k=limit
        )

    logger.info(
        "retrieval.rerank",
        candidate_count=outcome.candidate_count,
        kept_count=outcome.kept_count,
        top_score=outcome.top_score,
        fail_safe_fired=outcome.fail_safe_fired,
        requery_count=requery_count,
        reformulated_query=reformulated,
    )

    return {
        "results": outcome.ranked,
        "total": len(outcome.ranked),
        "no_strong_evidence": outcome.fail_safe_fired,
        "requery_count": requery_count,
    }


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
    user_id = payload.parameters.get("user_id")  # optional — scopes results

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            data = await _retrieve_and_rerank(query, limit, user_id, logger)
            results = data["results"]
            resp = _ok(
                trace_id=payload.trace_id,
                data=data,
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
    # Read the key live from the environment on every call — do not rely on
    # the module-level cache, which is computed once at import time.
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
    except Exception:  # noqa: BLE001
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
        return _error(payload.trace_id, "Parameter 'query' is required.")

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

    # Get adapters (filtered or default book/paper + Internet Archive set)
    adapters = _get_shadow_adapters(requested_indexes)

    if not adapters:
        resp = _ok(
            trace_id=payload.trace_id,
            data={"query": query, "total_results": 0, "results": []},
        )
        logger.log_response(status=resp.status)
        return resp

    # Query all selected adapters concurrently, gracefully handling failures
    all_results: list[SourceSearchResult] = []
    degraded = False

    async def _query(adapter):
        try:
            return await adapter.search(query, limit=limit, offset=offset)
        except Exception:  # noqa: BLE001 — each adapter may fail independently
            return None

    gathered = await asyncio.gather(*[_query(a) for a in adapters])
    for results in gathered:
        if results is None:
            degraded = True
        else:
            all_results.extend(results)

    # Deduplicate across source indexes, then rank book sources above web noise
    deduped = deduplicate(all_results)
    ranked = rank_shadow_results(deduped)

    # Apply limit
    ranked = ranked[:limit]

    # Serialize
    results_data = []
    citations: list[str] = []
    for r in ranked:
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
                source_indexes_db.append(_shadow_index_entry(adapter))
            # Dedupe by (type, identifier) — registry entries (appended last) win
            deduped: dict[tuple[str, str], dict[str, Any]] = {}
            for entry in source_indexes_db:
                key = (entry.get("type"), entry.get("identifier"))
                deduped[key] = entry
            resp = _ok(trace_id=payload.trace_id, data={"source_indexes": list(deduped.values())})
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
        source_indexes.append(_shadow_index_entry(adapter))

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
    payload_key = payload.parameters.get("payload_key")
    created_after = payload.parameters.get("created_after")
    created_before = payload.parameters.get("created_before")

    logger = build_audit_logger(payload, request, _auth, "search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="saimon_list_audit_log",
        limit=limit,
    )

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            conditions: list[str] = []
            params: list[Any] = []

            if service_filter:
                params.append(service_filter)
                conditions.append(f"service_name = ${len(params)}")
            if event_filter:
                params.append(event_filter)
                conditions.append(f"event_type = ${len(params)}")
            if payload_key:
                params.append(payload_key)
                conditions.append(f"payload ? ${len(params)}")
            if created_after:
                params.append(created_after)
                conditions.append(f"created_at >= ${len(params)}")
            if created_before:
                params.append(created_before)
                conditions.append(f"created_at <= ${len(params)}")

            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)
            sql = (
                "SELECT trace_id, service_name, event_type, payload, created_at "
                "FROM audit_log"
                + where
                + f" ORDER BY created_at DESC LIMIT ${len(params)}"
            )
            rows = await _db_pool.fetch(sql, *params)
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


# ---------------------------------------------------------------------------
# tool: download_fulltext
# ---------------------------------------------------------------------------

_DEFAULT_FULLTEXT_CONSENT = {
    "annas_archive",
    "libgen",
    "scihub",
    "internet_archive",
    "academic_torrents",
}


def _resolve_fulltext_consent() -> set[str]:
    """Parse the FULLTEXT_DOWNLOAD_CONSENT allowlist.

    Operator decision 2026-08-20: all five source indexes are eligible by
    default.  An explicitly-set env var narrows the allowlist.
    """
    raw = _os.environ.get("FULLTEXT_DOWNLOAD_CONSENT", "")
    if not raw.strip():
        return set(_DEFAULT_FULLTEXT_CONSENT)
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _shadow_sources_enabled() -> bool:
    return _os.environ.get("SHADOW_SOURCES_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _normalize_doi(doi: str) -> str:
    return (doi or "").strip().lower()


async def _download_fulltext_flow(
    db: Any,
    storage: Any,
    get_adapter: Any,
    *,
    doi: str | None,
    source: dict[str, Any] | None,
    fetch_only: bool,
    embed_fn: Any,
) -> dict[str, Any]:
    """Core full-text download + ingest flow (consent → fetch → extract → S3 → cache → persist).

    Returns a result dict; never raises.
    """
    from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult
    from research_shared.fulltext import (
        chunk_text,
        content_hash,
        extract_text,
        persist_fulltext_document,
        register_fulltext_content_types,
    )
    from research_shared.s3_storage import (
        ensure_ingested_column,
        mark_fulltext_ingested,
        store_shadow_fulltext,
    )
    from research_shared.text_quality import text_quality_ok, text_quality_score

    if not _shadow_sources_enabled():
        return {"ok": False, "blocked": True, "error": "shadow sources are disabled"}

    # ── resolve source identity ──
    resolved_source_index: str | None = None
    title = ""
    file_type: str | None = None
    download_url: str | None = None
    identifier: str | None = None

    if source and isinstance(source, dict):
        resolved_source_index = source.get("source_index")
        title = source.get("title") or ""
        file_type = source.get("file_type")
        download_url = source.get("download_url")
        identifier = source.get("identifier")
        if not doi:
            doi = source.get("doi")
    if not doi:
        return {"ok": False, "error": "either 'doi' or 'source' (with doi) is required"}

    canonical_doi = _normalize_doi(doi)

    # ── consent check ──
    consent = _resolve_fulltext_consent()
    if resolved_source_index is not None and resolved_source_index not in consent:
        return {
            "ok": False,
            "blocked": True,
            "error": f"source index '{resolved_source_index}' is not in FULLTEXT_DOWNLOAD_CONSENT",
        }

    # ── dedup: skip re-download only when ingestion COMPLETED ──
    # A cache row with full_text_path but no ingested_at means a prior run
    # failed between S3 upload and KG persist — we must re-ingest, not
    # short-circuit to a silent cache_hit.
    if db is not None:
        await ensure_ingested_column(db)
        cached = await db.fetchrow(
            "SELECT full_text_path, file_type, title, source_index, ingested_at "
            "FROM shadow_sources_cache WHERE doi = $1",
            canonical_doi,
        )
        if cached and cached.get("full_text_path") and cached.get("ingested_at"):
            return {
                "ok": True,
                "cache_hit": True,
                "s3_key": cached["full_text_path"],
                "document_node_id": None,
                "chunk_count": 0,
                "title": cached.get("title") or title,
                "source_index": cached.get("source_index") or resolved_source_index,
            }

    # ── determine source index when only a DOI was supplied ──
    if resolved_source_index is None:
        # Prefer a cached metadata row, else default to Sci-Hub for DOIs.
        if db is not None:
            row = await db.fetchrow(
                "SELECT source_index, title, file_type FROM shadow_sources_cache WHERE doi = $1",
                canonical_doi,
            )
            if row:
                resolved_source_index = row.get("source_index")
                title = title or row.get("title") or ""
                file_type = file_type or row.get("file_type")
        if resolved_source_index is None:
            resolved_source_index = "scihub"

    # ── consent check after source_index resolution ──
    if resolved_source_index not in consent:
        return {
            "ok": False,
            "blocked": True,
            "error": f"source index '{resolved_source_index}' is not in FULLTEXT_DOWNLOAD_CONSENT",
        }

    adapter = get_adapter(resolved_source_index)
    if adapter is None:
        return {"ok": False, "error": f"no adapter registered for source index '{resolved_source_index}'"}

    result = SourceSearchResult(
        type="academic_paper",
        identifier=identifier or f"doi:{canonical_doi}",
        doi=canonical_doi,
        title=title or canonical_doi,
        source_index=resolved_source_index,
        source_index_label=resolved_source_index,
        file_type=file_type,
        download_url=download_url,
    )

    # ── fetch (fail-closed) ──
    fetched: FulltextFetchResult | None = None
    try:
        fetched = await adapter.fetch_fulltext(result)
    except Exception:  # noqa: BLE001 — adapters must never throw
        fetched = None

    if fetched is None or fetched.data is None:
        return {
            "ok": False,
            "error": "full text not downloadable" + (
                f" (magnet link: {fetched.download_url})"
                if fetched is not None and fetched.download_url else ""
            ),
        }

    data = fetched.data
    fetched_type = fetched.file_type or file_type

    # ── extract text (fail-closed) ──
    text = extract_text(data, fetched_type)
    if not text:
        return {"ok": False, "error": "could not extract text from downloaded bytes"}

    # ── quality gate: reject garbled OCR before any S3/cache/KG write ──
    if not text_quality_ok(text):
        return {
            "ok": False,
            "error": "fulltext quality gate rejected the extracted text",
            "quality_rejected": True,
            "quality_score": round(text_quality_score(text), 4),
            "doi": canonical_doi,
        }

    # ── S3 upload + cache persistence ──
    try:
        s3_key = await store_shadow_fulltext(
            db,
            storage,
            doi=canonical_doi,
            title=title or canonical_doi,
            data=data,
            file_type=fetched_type,
            source_index=resolved_source_index,
        )
    except Exception as exc:  # noqa: BLE001 — unconfigured storage fails closed
        return {"ok": False, "error": f"S3 storage failed: {exc}"}

    if fetch_only:
        return {
            "ok": True,
            "fetch_only": True,
            "s3_key": s3_key,
            "document_node_id": None,
            "chunk_count": 0,
        }

    # ── chunk + embed + persist ──
    chunks = chunk_text(text)
    if not chunks:
        return {"ok": False, "error": "extracted text produced no chunks"}

    embeddings = [embed_fn(chunk) if embed_fn is not None else None for chunk in chunks]

    if db is not None:
        await register_fulltext_content_types(db)
        persisted = await persist_fulltext_document(
            db,
            doi=canonical_doi,
            title=title or canonical_doi,
            source_index=resolved_source_index,
            abstract=(text[:500] or None),
            s3_key=s3_key,
            content_hash_value=content_hash(data),
            fetched_at=_iso_now(),
            chunks=chunks,
            embeddings=embeddings,
        )
        await mark_fulltext_ingested(db, canonical_doi)
        return {
            "ok": True,
            "cache_hit": False,
            "s3_key": s3_key,
            "document_node_id": persisted["document_node_id"],
            "chunk_count": persisted["chunk_count"],
            "source_index": resolved_source_index,
        }

    return {
        "ok": True,
        "cache_hit": False,
        "s3_key": s3_key,
        "document_node_id": None,
        "chunk_count": len(chunks),
        "source_index": resolved_source_index,
    }


def _iso_now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


def _ingest_url_error(url: str) -> str | None:
    """Return why *url* may not be ingested, or None when it is allowed.

    Only public http(s) targets: a knowledge-graph service that fetches
    arbitrary user-supplied URLs must not be usable as an SSRF probe against
    loopback, link-local or private ranges.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "url must be http or https"
    host = parsed.hostname or ""
    if not host:
        return "url has no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return f"cannot resolve host {host!r}"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return f"host {host!r} resolved to an unparseable address"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return f"host {host!r} resolves to a non-public address"
    return None


BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
MAX_INGEST_TEXT_CHARS = 4_000_000
MIN_INGEST_TEXT_CHARS = 200


def _ingest_headers() -> dict[str, str]:
    """Headers for fetching a public document.

    A self-identifying bot user-agent is refused outright by a large share of
    .gov/.edu/trade sites (403/405), so the default presents a normal browser
    identity while still fetching only public URLs the caller supplied.
    Override with SAIMON_INGEST_USER_AGENT.
    """
    return {
        "User-Agent": _os.environ.get("SAIMON_INGEST_USER_AGENT", BROWSER_UA),
        "Accept": (
            "text/html,application/xhtml+xml,application/pdf,"
            "application/epub+zip;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }


async def _fetch_document(url: str, max_bytes: int = 40 * 1024 * 1024) -> tuple[bytes, str | None]:
    """Fetch *url* and return (bytes, file_type). Raises on refusal/oversize."""
    from urllib.parse import urlparse

    import httpx

    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client, client.stream(
        "GET", url, headers=_ingest_headers()
    ) as resp:
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise ValueError(f"document exceeds {max_bytes} bytes")

    file_type = {
        "application/pdf": "pdf",
        "application/x-pdf": "pdf",
        "text/html": "html",
        "application/xhtml+xml": "html",
        "text/plain": "txt",
        "application/epub+zip": "epub",
    }.get(ctype)
    if file_type is None and urlparse(url).path.lower().endswith(".pdf"):
        file_type = "pdf"
    return bytes(buf), file_type


@app.post("/tools/ingest_document")
async def ingest_document(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Fetch a public document (PDF/HTML/EPUB) by URL and ingest it into the KG.

    The lawful way in: the caller supplies a URL they are entitled to read, and
    Saimon stores the extracted text as ``fulltext_document`` + ``fulltext_chunk``
    nodes (embedded for retrieval, tagged with collection/unit_id).
    """
    _require_auth(request)

    url = str(payload.parameters.get("url") or "").strip()
    title = payload.parameters.get("title")
    collection = str(payload.parameters.get("collection") or "research")
    provided_text = payload.parameters.get("text")

    if not url:
        return _error(payload.trace_id, "Parameter 'url' is required.")
    refusal = _ingest_url_error(url)
    if refusal:
        return _error(payload.trace_id, f"Refusing to ingest: {refusal}.")
    if _db_pool is None:
        return _error(payload.trace_id, "Database not available.")

    from research_shared.fulltext import (
        chunk_text,
        content_hash,
        extract_text,
        persist_fulltext_document,
        register_fulltext_content_types,
    )
    from research_shared.text_quality import text_quality_ok, text_quality_score

    logger = AuditLogger(trace_id=payload.trace_id, service_name="search-mcp")
    logger.log_request(
        content_type=payload.content_type, tool="ingest_document", url=url
    )

    try:
        if provided_text is not None:
            if not isinstance(provided_text, str):
                return _error(payload.trace_id, "Parameter 'text' must be a string.")
            text = provided_text.strip()
            if len(text) < MIN_INGEST_TEXT_CHARS:
                return _error(
                    payload.trace_id,
                    f"Parameter 'text' must be at least {MIN_INGEST_TEXT_CHARS} characters.",
                )
            if len(text) > MAX_INGEST_TEXT_CHARS:
                return _error(
                    payload.trace_id,
                    f"Parameter 'text' exceeds {MAX_INGEST_TEXT_CHARS} characters.",
                )
            file_type = "txt"
            data = text.encode("utf-8")
        else:
            data, file_type = await _fetch_document(url)
            text = extract_text(data, file_type)
    except Exception as exc:  # noqa: BLE001 — a fetch failure is an error response
        return _error(payload.trace_id, f"download failed: {exc}")

    if not text:
        return _error(
            payload.trace_id,
            f"could not extract text (file_type={file_type or 'unknown'})",
        )
    if not text_quality_ok(text):
        return _error(
            payload.trace_id,
            "quality gate rejected the extracted text "
            f"(score={round(text_quality_score(text), 4)})",
        )

    chunks = chunk_text(text)
    if not chunks:
        return _error(payload.trace_id, "extracted text produced no chunks")

    from research_shared.embedding import EmbeddingConfig, embed_many_local

    emb_cfg = EmbeddingConfig.from_env()
    embeddings = embed_many_local(
        chunks, emb_cfg.model, emb_cfg.dimensions, emb_cfg.model_path or None
    )
    if all(vector is None for vector in embeddings):
        # Fail closed: chunks stored without embeddings are invisible to the
        # vector path, so a "successful" ingest would silently add nothing to
        # retrieval. Name the backend instead of writing unsearchable rows.
        return _error(
            payload.trace_id,
            "embedding backend unavailable: no chunk could be embedded "
            f"(model={emb_cfg.model}, path={emb_cfg.model_path or 'default'})",
        )

    await register_fulltext_content_types(_db_pool)
    persisted = await persist_fulltext_document(
        _db_pool,
        doi="url:" + url,
        title=str(title or url.rsplit("/", 1)[-1] or url),
        source_index="url_import",
        abstract=text[:500],
        s3_key=url,
        content_hash_value=content_hash(data),
        fetched_at=_iso_now(),
        chunks=chunks,
        embeddings=embeddings,
        collection=collection,
    )

    logger.log_response(status="success", citations_count=persisted["chunk_count"])
    return _ok(
        trace_id=payload.trace_id,
        data={
            "url": url,
            "title": title or url.rsplit("/", 1)[-1],
            "collection": collection,
            "document_node_id": persisted["document_node_id"],
            "chunk_count": persisted["chunk_count"],
            "chars": len(text),
        },
        citations=[persisted["document_node_id"]],
    )


@app.post("/tools/download_fulltext")
async def download_fulltext(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Download a document's full text to object storage and ingest into the KG."""
    _require_auth(request)

    doi = payload.parameters.get("doi")
    source = payload.parameters.get("source")
    fetch_only = bool(payload.parameters.get("fetch_only", False))

    if not doi and not source:
        return _error(payload.trace_id, "Either 'doi' or 'source' is required.")

    logger = AuditLogger(trace_id=payload.trace_id, service_name="search-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="download_fulltext",
        doi=doi,
        fetch_only=fetch_only,
    )

    from research_shared.embedding import embed_local
    from research_shared.s3_storage import S3Storage

    storage = S3Storage.from_env()
    result = await _download_fulltext_flow(
        _db_pool,
        storage,
        _shadow_registry.get,
        doi=doi,
        source=source,
        fetch_only=fetch_only,
        embed_fn=embed_local,
    )

    if result.get("blocked"):
        logger.warning(
            "fulltext_download_blocked",
            doi=doi,
            reason=result.get("error"),
        )
        resp = _error(payload.trace_id, result.get("error") or "full-text download blocked")
        logger.log_response(status=resp.status, blocked=True)
        return resp

    if result.get("quality_rejected"):
        logger.warning(
            "fulltext_quality_rejected",
            doi=result.get("doi") or doi,
            score=result.get("quality_score"),
        )
        resp = _error(payload.trace_id, result.get("error") or "full-text quality gate rejected")
        logger.log_response(status=resp.status)
        return resp

    if not result.get("ok"):
        logger.warning("fulltext_download_failed", doi=doi, reason=result.get("error"))
        resp = _error(payload.trace_id, result.get("error") or "full-text download failed")
        logger.log_response(status=resp.status)
        return resp

    logger.info(
        "fulltext_download_complete",
        doi=doi,
        cache_hit=result.get("cache_hit", False),
        fetch_only=result.get("fetch_only", False),
        chunk_count=result.get("chunk_count", 0),
    )
    resp = _ok(
        trace_id=payload.trace_id,
        data=result,
        citations=[result.get("document_node_id")] if result.get("document_node_id") else None,
    )
    logger.log_response(status=resp.status, chunk_count=result.get("chunk_count", 0))
    return resp
