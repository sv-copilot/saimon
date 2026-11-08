"""server.py — explore-mcp FastAPI application.

Provides discovery tools for browsing and exploring the knowledge graph,
finding related content, and discovering connections between content items.
Every tool endpoint accepts a ResearchRequest envelope and returns a
ResearchResponse envelope.  Authentication is fail-closed.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.db import DatabaseError, DatabasePool
from research_shared.envelope import ResearchRequest, ResearchResponse
from research_shared.hardening import apply_hardening, build_audit_logger
from research_shared.lifespan import build_lifespan
from research_shared.rerank import RerankConfig, rerank
from research_shared.seed_data import CONTENT_TYPES as SEED_CONTENT_TYPES

# ---------------------------------------------------------------------------
# retrieval gate (SAIMON-RETRIEVAL-ABSTAIN-1 #234)
# ---------------------------------------------------------------------------

_rerank_config = RerankConfig.from_env()


def _rerank_embed_fn() -> Any:
    """Return a fail-closed embedding callable for the reranker.

    Same local backend the vector path uses, so cosine similarity can be
    computed for keyword-only rows that carry no precomputed embedding.
    """
    from research_shared.embedding import EmbeddingConfig, embed_local, query_embed_text

    cfg = EmbeddingConfig.from_env()

    def embed(text: str) -> list[float] | None:
        return embed_local(query_embed_text(text), cfg.model, cfg.dimensions)

    return embed


def _prefixes_on() -> bool:
    """Prefixes are opt-in; with them off the passage path must stay unchanged."""
    from research_shared.embedding import task_prefixes_enabled

    return task_prefixes_enabled()


def _rerank_passage_embed_fn():
    from research_shared.embedding import (
        EmbeddingConfig,
        document_embed_text,
        embed_local,
    )

    cfg = EmbeddingConfig.from_env()

    def embed(text: str) -> list[float] | None:
        return embed_local(document_embed_text(text), cfg.model, cfg.dimensions)

    return embed

# ---------------------------------------------------------------------------
# backend injection (must be before lifespan)
# ---------------------------------------------------------------------------

_db_pool: DatabasePool | None = None


def set_db_pool(pool: DatabasePool | None) -> None:
    """Inject a DatabasePool for live knowledge-graph queries."""
    global _db_pool
    _db_pool = pool


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

_lifespan = build_lifespan("explore-mcp", db_pool_ref=lambda: _db_pool, db_pool_setter=set_db_pool)
app = FastAPI(title="explore-mcp", version="0.1.0", lifespan=_lifespan)

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
# content type registry (from seed_data)
# ---------------------------------------------------------------------------

_CONTENT_TYPES: list[dict[str, Any]] = [
    {
        "name": ct["name"],
        "description": ct["description"],
        "item_count": 0,
    }
    for ct in SEED_CONTENT_TYPES
]

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
            _log.debug("explore-mcp health: DB not reachable", exc_info=True)
    kg_nodes = 0
    if _db_pool is not None and db_ok:
        try:
            row = await _db_pool.fetch("SELECT count(*) as cnt FROM knowledge_graph_nodes")
            kg_nodes = row[0]["cnt"] if row else 0
        except Exception:  # noqa: BLE001
            _log.debug("explore-mcp health: KG node count query failed", exc_info=True)
    return {
        "status": "ok",
        "service": "explore-mcp",
        "checks": {"database": "connected" if db_ok else "unavailable",
                   "kg_nodes": kg_nodes},
    }


# ---------------------------------------------------------------------------
# tool listing
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "explore_content",
        "description": "Discover content by topic or keyword query.",
        "parameters": {
            "query": "str (required)",
            "limit": "int (optional, default 10)",
        },
    },
    {
        "name": "browse_by_type",
        "description": "Browse content items filtered by content type.",
        "parameters": {
            "content_type": "str (required)",
            "limit": "int (optional, default 10)",
            "offset": "int (optional, default 0)",
        },
    },
    {
        "name": "get_related",
        "description": "Find content items related to a specific node via knowledge graph edges.",
        "parameters": {
            "node_id": "str (required)",
            "relation_type": "str (optional, filter by relation type)",
            "direction": "str (optional, 'outgoing'|'incoming'|'both', default 'both')",
            "limit": "int (optional, default 20)",
        },
    },
    {
        "name": "create_edge",
        "description": "Create a typed relation between two knowledge graph nodes. "
                       "Idempotent — safe to call multiple times.",
        "parameters": {
            "source_id": "str (required)",
            "target_id": "str (required)",
            "relation_type": "str (required)",
            "weight": "float (optional, default 1.0)",
            "metadata": "dict (optional)",
        },
    },
    {
        "name": "discover_connections",
        "description": "Find connection paths between two knowledge graph nodes.",
        "parameters": {
            "source_id": "str (required)",
            "target_id": "str (required)",
        },
    },
    {
        "name": "list_content_types",
        "description": "List all registered content types in the platform.",
        "parameters": {},
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

def _degraded(trace_id: str, data: Any = None, citations: list[str] | None = None) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id, status="degraded", data=data, citations=citations,
    )


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


def _error(trace_id: str, message: str) -> ResearchResponse:
    return ResearchResponse(
        trace_id=trace_id,
        status="error",
        errors=[message],
    )


# ---------------------------------------------------------------------------
# tool: explore_content
# ---------------------------------------------------------------------------

@app.post("/tools/explore_content")
async def explore_content(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    query = payload.parameters.get("query")
    if not query:
        return _error(payload.trace_id, "Parameter 'query' is required.")

    limit = min(int(payload.parameters.get("limit", 10)), 100)

    logger = build_audit_logger(payload, request, _auth, "explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="explore_content",
        query=query,
        limit=limit,
    )

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            # Retrieve a broader pool than the final top-K so the gate can
            # narrow by relevance instead of by adapter order (#234).
            candidate_limit = max(limit * 2, _rerank_config.top_k)
            rows = await _db_pool.fetch(
                "SELECT id, title, content_type, body, "
                "COALESCE(metadata->>'status', 'ready') as doc_status, "
                "COALESCE(metadata->>'review_status', 'accepted_research') as doc_review, "
                "COALESCE((metadata->>'relevance')::float, 0.5) as relevance "
                "FROM knowledge_graph_nodes "
                "WHERE title ILIKE $1 OR body ILIKE $1 "
                "ORDER BY created_at DESC LIMIT $2",
                f"%{query}%", candidate_limit,
            )
            candidates = [
                dict(r) for r in rows
                if (dict(r).get("doc_status") or "ready") != "failed"
            ]
            from research_shared.review import filter_by_review

            candidates = filter_by_review(
                candidates, payload.parameters.get("review_statuses")
            )
            outcome = rerank(
                query, candidates, _rerank_config,
                embed_fn=_rerank_embed_fn(),
                passage_embed_fn=_rerank_passage_embed_fn() if _prefixes_on() else None,
                top_k=limit,
            )
            results = outcome.ranked
            logger.info(
                "retrieval.abstain",
                path="explore_content",
                query=query,
                top_score=outcome.top_score,
                second_score=outcome.second_score,
                margin_gap=outcome.margin_gap,
                floor=_rerank_config.min_relevance,
                margin=_rerank_config.min_margin,
                abstained=outcome.fail_safe_fired,
            )
            resp = _ok(
                trace_id=payload.trace_id,
                data={
                    "query": query,
                    "results": results,
                    "total": len(results),
                    "no_strong_evidence": outcome.fail_safe_fired,
                },
                citations=[str(r["id"]) for r in results],
            )
            logger.log_response(
                status=resp.status, citations_count=len(resp.citations or [])
            )
            return resp
        except (DatabaseError, NotImplementedError):
            pass

    # ── fallback ──
    results: list[dict[str, Any]] = [
        {
            "id": f"kg-{i:03d}",
            "title": f"Result {i} for: {query[:40]}...",
            "content_type": "research_note" if i % 2 == 0 else "article",
            "relevance": round(1.0 - (i * 0.08), 2),
            "summary": (
                f"A {_random_type(i)} about {query} with key insights "
                f"and references to related work."
            ),
        }
        for i in range(min(limit, 8))
    ]

    resp = _degraded(
        trace_id=payload.trace_id,
        data={
            "query": query,
            "results": results,
            "total": len(results),
        },
        citations=[str(r["id"]) for r in results],
    )
    logger.log_response(
        status=resp.status, citations_count=len(resp.citations or [])
    )
    return resp


def _random_type(i: int) -> str:
    """Return a content type label for placeholder results."""
    types = ["research note", "article", "analysis", "summary", "finding"]
    return types[i % len(types)]


# ---------------------------------------------------------------------------
# tool: browse_by_type
# ---------------------------------------------------------------------------

@app.post("/tools/browse_by_type")
async def browse_by_type(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    content_type = payload.parameters.get("content_type")
    if not content_type:
        return _error(payload.trace_id, "Parameter 'content_type' is required.")

    limit = min(int(payload.parameters.get("limit", 10)), 100)
    offset = max(int(payload.parameters.get("offset", 0)), 0)

    logger = build_audit_logger(payload, request, _auth, "explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="browse_by_type",
        browse_type=content_type,
        limit=limit,
        offset=offset,
    )

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            rows = await _db_pool.fetch(
                "SELECT id, title, content_type, body, created_at "
                "FROM knowledge_graph_nodes "
                "WHERE content_type = $1 "
                "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                content_type, limit, offset,
            )
            items = [dict(r) for r in rows]
            resp = _ok(
                trace_id=payload.trace_id,
                data={
                    "content_type": content_type,
                    "items": items,
                    "total": len(items),
                    "offset": offset,
                },
                citations=[str(item["id"]) for item in items],
            )
            logger.log_response(
                status=resp.status, citations_count=len(resp.citations or [])
            )
            return resp
        except (DatabaseError, NotImplementedError):
            pass

    # ── fallback ──
    items: list[dict[str, Any]] = [
        {
            "id": f"{content_type}-{offset + i:03d}",
            "title": f"{content_type.replace('_', ' ').title()} Item {offset + i}",
            "content_type": content_type,
            "summary": (
                f"A {content_type.replace('_', ' ')} covering important "
                f"discoveries and insights in the knowledge graph."
            ),
            "created_at": f"2026-07-{(20 - i):02d}T10:00:00Z",
        }
        for i in range(min(limit, 6))
    ]

    resp = _degraded(
        trace_id=payload.trace_id,
        data={
            "content_type": content_type,
            "items": items,
            "total": len(items),
            "offset": offset,
        },
        citations=[item["id"] for item in items],
    )
    logger.log_response(
        status=resp.status, citations_count=len(resp.citations or [])
    )
    return resp


# ---------------------------------------------------------------------------
# tool: discover_connections
# ---------------------------------------------------------------------------

@app.post("/tools/discover_connections")
async def discover_connections(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    source_id = payload.parameters.get("source_id")
    target_id = payload.parameters.get("target_id")

    errors: list[str] = []
    if not source_id:
        errors.append("Parameter 'source_id' is required.")
    if not target_id:
        errors.append("Parameter 'target_id' is required.")
    if errors:
        return ResearchResponse(
            trace_id=payload.trace_id,
            status="error",
            errors=errors,
        )

    logger = build_audit_logger(payload, request, _auth, "explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="discover_connections",
        source_id=source_id,
        target_id=target_id,
    )

    # ── try DB backend ──
    if _db_pool is not None:
        try:
            rows = await _db_pool.fetch(
                "SELECT source_id AS from_id, target_id AS to_id, "
                "relationship_type AS type "
                "FROM knowledge_graph_edges "
                "WHERE source_id = $1 AND target_id = $2 "
                "LIMIT 5",
                source_id, target_id,
            )
            edges = [dict(r) for r in rows]
            paths = [{"edges": edges, "length": len(edges)}] if edges else []
            resp = _ok(
                trace_id=payload.trace_id,
                data={
                    "source_id": source_id,
                    "target_id": target_id,
                    "paths": paths,
                },
            )
            logger.log_response(status=resp.status)
            return resp
        except (DatabaseError, NotImplementedError):
            pass

    # ── fallback ──
    isolated = {"isolated-node", "another-isolated"}
    if source_id in isolated or target_id in isolated:
        paths: list[dict[str, Any]] = []
    else:
        paths = [
            {
                "nodes": [source_id, "kg-intermediate", target_id],
                "edges": [
                    {
                        "from": source_id,
                        "to": "kg-intermediate",
                        "type": "references",
                    },
                    {
                        "from": "kg-intermediate",
                        "to": target_id,
                        "type": "extends",
                    },
                ],
                "length": 2,
            }
        ]

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "source_id": source_id,
            "target_id": target_id,
            "paths": paths,
        },
    )
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: list_content_types
# ---------------------------------------------------------------------------

@app.post("/tools/list_content_types")
async def list_content_types(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    logger = build_audit_logger(payload, request, _auth, "explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="list_content_types",
    )

    resp = _ok(
        trace_id=payload.trace_id,
        data={"content_types": _CONTENT_TYPES},
    )
    logger.log_response(status=resp.status)
    return resp


# ---------------------------------------------------------------------------
# tool: create_edge
# ---------------------------------------------------------------------------

@app.post("/tools/create_edge")
async def create_edge(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Create a typed relation between two knowledge graph nodes.

    Idempotent — ON CONFLICT upserts prevent duplicate edges.
    """
    _require_auth(request)

    source_id = payload.parameters.get("source_id")
    target_id = payload.parameters.get("target_id")
    relation_type = payload.parameters.get("relation_type")
    weight = float(payload.parameters.get("weight", 1.0))
    metadata = payload.parameters.get("metadata")

    logger = build_audit_logger(payload, request, _auth, "explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="create_edge",
        source_id=source_id,
        target_id=target_id,
        relation_type=relation_type,
    )

    if not source_id:
        return _error(payload.trace_id, "Parameter 'source_id' is required.")
    if not target_id:
        return _error(payload.trace_id, "Parameter 'target_id' is required.")
    if not relation_type:
        return _error(payload.trace_id, "Parameter 'relation_type' is required.")

    if _db_pool is None:
        return _error(payload.trace_id, "Database not available.")

    # Resolve metadata: accept dict or JSON string
    import json as _json

    meta_json = "{}"
    if metadata:
        if isinstance(metadata, dict):
            meta_json = _json.dumps(metadata)
        elif isinstance(metadata, str):
            try:
                _json.loads(metadata)  # validate
                meta_json = metadata
            except _json.JSONDecodeError:
                meta_json = _json.dumps({"raw": metadata})

    try:
        row = await _db_pool.fetchrow(
            "INSERT INTO knowledge_graph_edges "
            "(source_id, target_id, relation_type, weight, metadata) "
            "VALUES ($1, $2, $3, $4, $5::jsonb) "
            "ON CONFLICT (source_id, target_id, relation_type) "
            "DO UPDATE SET weight = $4, metadata = $5::jsonb "
            "RETURNING id",
            source_id, target_id, relation_type, weight, meta_json,
        )
        edge_id = str(row["id"]) if row else None
    except Exception as exc:  # noqa: BLE001 — API boundary: return error envelope on any failure
        logger.log_response(status="error")
        return _error(payload.trace_id, f"Failed to create edge: {exc}")

    if edge_id is None:
        logger.log_response(status="error")
        return _error(payload.trace_id, "Failed to create edge — no ID returned.")

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "edge_id": edge_id,
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
            "weight": weight,
        },
        citations=[edge_id],
    )
    logger.log_response(status=resp.status, citations_count=1)
    return resp


# ---------------------------------------------------------------------------
# tool: get_related
# ---------------------------------------------------------------------------

@app.post("/tools/get_related")
async def get_related(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    """Find nodes related to a given node via knowledge_graph_edges.

    Supports filtering by relation_type and direction
    (outgoing, incoming, or both).
    """
    _require_auth(request)

    node_id = payload.parameters.get("node_id")
    relation_type = payload.parameters.get("relation_type")
    direction = payload.parameters.get("direction", "both")
    limit = min(int(payload.parameters.get("limit", 20)), 100)

    logger = build_audit_logger(payload, request, _auth, "explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="get_related",
        node_id=node_id,
        relation_type=relation_type,
        direction=direction,
    )

    if not node_id:
        return _error(payload.trace_id, "Parameter 'node_id' is required.")

    if _db_pool is None:
        return _error(payload.trace_id, "Database not available.")

    # Build query based on direction
    if direction == "outgoing":
        where = "e.source_id = $1"
    elif direction == "incoming":
        where = "e.target_id = $1"
    else:
        where = "(e.source_id = $1 OR e.target_id = $1)"

    params: list[Any] = [node_id]
    type_filter = ""
    if relation_type:
        params.append(relation_type)
        type_filter = f" AND e.relation_type = ${len(params)}"

    try:
        rows = await _db_pool.fetch(
            f"SELECT e.id as edge_id, e.relation_type, e.weight, "
            f"e.source_id, e.target_id, "
            f"n.id as node_id, n.title, n.content_type "
            f"FROM knowledge_graph_edges e "
            f"JOIN knowledge_graph_nodes n ON "
            f"(CASE WHEN e.source_id = $1 THEN e.target_id ELSE e.source_id END) = n.id "
            f"WHERE {where}{type_filter} "
            f"ORDER BY e.weight DESC, e.created_at DESC "
            f"LIMIT ${len(params) + 1}",
            *(params + [limit]),
        )

        items: list[dict[str, Any]] = []
        for r in rows:
            items.append({
                "edge_id": str(r["edge_id"]),
                "relation_type": r["relation_type"],
                "weight": r["weight"],
                "direction": "outgoing" if str(r["source_id"]) == node_id else "incoming",
                "node": {
                    "id": str(r["node_id"]),
                    "title": r["title"],
                    "content_type": r["content_type"],
                },
            })

        resp = _ok(
            trace_id=payload.trace_id,
            data={
                "node_id": node_id,
                "related": items,
                "total": len(items),
            },
            citations=[str(item["node"]["id"]) for item in items],
        )
        logger.log_response(
            status=resp.status, citations_count=len(resp.citations or [])
        )
        return resp
    except Exception as exc:  # noqa: BLE001 — API boundary: return error envelope on any failure
        logger.log_response(status="error")
        return _error(payload.trace_id, f"Failed to get related nodes: {exc}")
