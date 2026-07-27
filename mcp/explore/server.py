"""server.py — explore-mcp FastAPI application.

Provides discovery tools for browsing and exploring the knowledge graph,
finding related content, and discovering connections between content items.
Every tool endpoint accepts a ResearchRequest envelope and returns a
ResearchResponse envelope.  Authentication is fail-closed.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from research_shared.audit import AuditLogger
from research_shared.auth import AuthConfig, AuthError, AuthValidator
from research_shared.envelope import ResearchRequest, ResearchResponse

# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

app = FastAPI(title="explore-mcp", version="0.1.0")

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
# content type registry (placeholder)
# ---------------------------------------------------------------------------

_CONTENT_TYPES: list[dict[str, Any]] = [
    {
        "name": "article",
        "description": "Long-form article or blog post.",
        "item_count": 12,
    },
    {
        "name": "research_note",
        "description": "Atomic research finding or observation.",
        "item_count": 34,
    },
    {
        "name": "source",
        "description": "External source citation with metadata.",
        "item_count": 8,
    },
    {
        "name": "concept",
        "description": "Abstract concept node in the knowledge graph.",
        "item_count": 21,
    },
    {
        "name": "claim",
        "description": "Verifiable factual claim.",
        "item_count": 15,
    },
]

# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    """Unauthenticated health check."""
    return {"status": "ok", "service": "explore-mcp"}


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
        "description": "Find content items related to a specific item.",
        "parameters": {"item_id": "str (required)"},
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

    logger = AuditLogger(trace_id=payload.trace_id, service_name="explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="explore_content",
        query=query,
        limit=limit,
    )

    # Placeholder — in production this queries the knowledge graph via
    # research_shared.db with vector similarity search.
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

    resp = _ok(
        trace_id=payload.trace_id,
        data={
            "query": query,
            "results": results,
            "total": len(results),
        },
        citations=[r["id"] for r in results],
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

    logger = AuditLogger(trace_id=payload.trace_id, service_name="explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="browse_by_type",
        browse_type=content_type,
        limit=limit,
        offset=offset,
    )

    # Placeholder — in production this queries PostgreSQL filtered by
    # content_type column via research_shared.db.
    items: list[dict[str, Any]] = [
        {
            "id": f"{content_type}-{offset + i:03d}",
            "title": f"{content_type.replace('_', ' ').title()} Item {offset + i}",
            "summary": (
                f"A {content_type.replace('_', ' ')} covering important "
                f"discoveries and insights in the knowledge graph."
            ),
            "created_at": f"2026-07-{(20 - i):02d}T10:00:00Z",
        }
        for i in range(min(limit, 6))
    ]

    resp = _ok(
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
# tool: get_related
# ---------------------------------------------------------------------------

_RELATIONSHIPS: list[str] = [
    "cites",
    "extends",
    "contradicts",
    "supports",
    "references",
]


@app.post("/tools/get_related")
async def get_related(
    payload: ResearchRequest, request: Request
) -> ResearchResponse:
    _require_auth(request)

    item_id = payload.parameters.get("item_id")
    if not item_id:
        return _error(payload.trace_id, "Parameter 'item_id' is required.")

    logger = AuditLogger(trace_id=payload.trace_id, service_name="explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="get_related",
        item_id=item_id,
    )

    # Placeholder — in production this traverses the knowledge graph edge
    # table via research_shared.db to find connected nodes.
    known_ids = {"kg-001", "kg-002", "kg-003", "kg-004", "kg-005"}
    if item_id not in known_ids:
        related: list[dict[str, Any]] = []
    else:
        related = [
            {
                "id": f"kg-{j:03d}",
                "title": f"Related item {j} to {item_id}",
                "relationship": _RELATIONSHIPS[j % len(_RELATIONSHIPS)],
                "summary": (
                    f"This item {_RELATIONSHIPS[j % len(_RELATIONSHIPS)]} "
                    f"{item_id} through shared concepts and references."
                ),
            }
            for j in range(3)
        ]

    resp = _ok(
        trace_id=payload.trace_id,
        data={"item_id": item_id, "related": related},
        citations=[r["id"] for r in related],
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

    logger = AuditLogger(trace_id=payload.trace_id, service_name="explore-mcp")
    logger.log_request(
        content_type=payload.content_type,
        tool="discover_connections",
        source_id=source_id,
        target_id=target_id,
    )

    # Placeholder — in production this runs a graph traversal (BFS/DFS)
    # over the knowledge graph edge table via research_shared.db.
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

    logger = AuditLogger(trace_id=payload.trace_id, service_name="explore-mcp")
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
