#!/usr/bin/env python3
"""saimon_mcp_proxy.py — MCP stdio proxy for Saimon REST endpoints.

Makes Saimon's 6 MCPs (search, generate, export, evaluate, verify, explore)
available as native MCP tools to VS Code agents.

Usage (in VS Code MCP config):
    {
      "saimon-researcher": {
        "transport": "stdio",
        "command": "python3",
        "args": ["tools/saimon-mcp-proxy/proxy.py"],
        "env": {
          "SAIMON_BASE_URL": "https://mcp-staging.spencervaradi.com/saimon",
          "SAIMON_API_KEY": "sk-test-search-key"
        }
      }
    }

For local dev, set SAIMON_BASE_URL per service or use direct ports:
    SAIMON_SEARCH_URL=http://127.0.0.1:8001
    SAIMON_GENERATE_URL=http://127.0.0.1:8002
    ...

If SAIMON_BASE_URL is set (Caddy mode), all tools route through it
with /{service}/tools/... paths.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("SAIMON_BASE_URL", "")
API_KEY = os.environ.get("SAIMON_API_KEY", "sk-test-search-key")

# Per-service direct URLs (used when BASE_URL is not set)
SERVICE_URLS: dict[str, str] = {
    "search": os.environ.get("SAIMON_SEARCH_URL", "http://127.0.0.1:8001"),
    "generate": os.environ.get("SAIMON_GENERATE_URL", "http://127.0.0.1:8002"),
    "export": os.environ.get("SAIMON_EXPORT_URL", "http://127.0.0.1:8003"),
    "evaluate": os.environ.get("SAIMON_EVALUATE_URL", "http://127.0.0.1:8004"),
    "verify": os.environ.get("SAIMON_VERIFY_URL", "http://127.0.0.1:8005"),
    "explore": os.environ.get("SAIMON_EXPLORE_URL", "http://127.0.0.1:8006"),
}


def _build_url(service: str, path: str) -> str:
    """Build the full URL for a tool call."""
    if BASE_URL:
        # Caddy mode: https://staging/saimon/search/tools/...
        return f"{BASE_URL}/{service}{path}"
    # Direct mode: http://127.0.0.1:8001/tools/...
    return f"{SERVICE_URLS[service]}{path}"


# Map tool names to (service, method, path, body_template)
# Paths are the tool endpoint paths (e.g., /tools/search_knowledge_graph)
TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    # ── Search Tools ────────────────────────────────────────────
    "saimon_search_scholarly": {
        "description": (
            "Search shadow library sources (Anna's Archive, LibGen, Sci-Hub, "
            "Internet Archive, Academic Torrents) for academic papers, books, "
            "and datasets. Returns ranked results with DOIs, titles, authors, "
            "years, and source attribution."
        ),
        "service": "search",
        "method": "POST",
        "path": "/tools/search_shadow_libraries",
        "body_template": {
            "content_type": "search",
            "parameters": {"query": "{query}", "limit": "{limit}"},
        },
    },
    "saimon_search_knowledge_graph": {
        "description": (
            "Search the PostgreSQL knowledge graph for previously stored "
            "research notes, verifications, and observations."
        ),
        "service": "search",
        "method": "POST",
        "path": "/tools/search_knowledge_graph",
        "body_template": {
            "content_type": "search",
            "parameters": {"query": "{query}", "limit": "{limit}"},
        },
    },
    "saimon_list_sources": {
        "description": (
            "List all available source indexes including knowledge graph "
            "and shadow library sources. Shows tier (S/A/B) and status."
        ),
        "service": "search",
        "method": "POST",
        "path": "/tools/list_source_indexes",
        "body_template": {"content_type": "search"},
    },

    # ── Verify Tools ────────────────────────────────────────────
    "saimon_verify_claim": {
        "description": (
            "Verify a factual claim using 5 corroboration methods. "
            "Searches shadow libraries for evidence, then uses DeepSeek "
            "LLM to analyze the claim. Returns supported/refuted/inconclusive "
            "with confidence scores and evidence citations."
        ),
        "service": "verify",
        "method": "POST",
        "path": "/tools/verify_claim",
        "body_template": {
            "content_type": "verify",
            "parameters": {"claim": "{claim}", "use_shadow_sources": True},
        },
    },
    "saimon_list_verification_methods": {
        "description": (
            "List all verification methods with descriptions and reliability "
            "scores. Includes source_corroboration, logical_consistency, "
            "authority_check, temporal_validity, shadow_source_corroboration."
        ),
        "service": "verify",
        "method": "POST",
        "path": "/tools/list_verification_methods",
        "body_template": {"content_type": "verify"},
    },

    # ── Generate Tools ──────────────────────────────────────────
    "saimon_generate_content": {
        "description": (
            "Generate research content using DeepSeek LLM. Supports 14 content "
            "types: blog_post, summary, research_note, white_paper, case_study, "
            "bibliography, social_post, email_draft, press_release, proposal, "
            "tutorial, product_review, meeting_notes, job_posting. "
            "Optional: tone, audience, max_length, depth, format."
        ),
        "service": "generate",
        "method": "POST",
        "path": "/tools/generate_content",
        "body_template": {
            "content_type": "{content_type}",
            "parameters": {"prompt": "{prompt}", "tone": "{tone}"},
        },
    },
    "saimon_list_content_types": {
        "description": (
            "List all 14 registered content types with their parameter schemas "
            "and voice profiles."
        ),
        "service": "generate",
        "method": "POST",
        "path": "/tools/list_content_types",
        "body_template": {"content_type": "generate"},
    },

    # ── Evaluate Tools ──────────────────────────────────────────
    "saimon_evaluate_content": {
        "description": (
            "Score generated content against quality criteria (accuracy, "
            "completeness, clarity, relevance, sourcing). Returns scored "
            "results with per-criterion breakdown."
        ),
        "service": "evaluate",
        "method": "POST",
        "path": "/tools/evaluate_content",
        "body_template": {
            "content_type": "evaluate",
            "parameters": {"content": "{content}", "criteria": "{criteria}"},
        },
    },

    # ── Explore Tools ───────────────────────────────────────────
    "saimon_explore_content": {
        "description": (
            "Discover content in the knowledge graph by topic or keyword. "
            "Finds related research notes, verifications, and observations."
        ),
        "service": "explore",
        "method": "POST",
        "path": "/tools/explore_content",
        "body_template": {
            "content_type": "explore",
            "parameters": {"query": "{query}"},
        },
    },
    "saimon_browse_by_type": {
        "description": (
            "Browse knowledge graph content filtered by type "
            "(research_note, verification, blog_post, etc.)."
        ),
        "service": "explore",
        "method": "POST",
        "path": "/tools/browse_by_type",
        "body_template": {
            "content_type": "explore",
            "parameters": {"content_type": "{type_name}"},
        },
    },

    # ── Export Tools ────────────────────────────────────────────
    "saimon_export_content": {
        "description": (
            "Format content into a specified output format (markdown, "
            "plain_text, json, html)."
        ),
        "service": "export",
        "method": "POST",
        "path": "/tools/export_content",
        "body_template": {
            "content_type": "export",
            "parameters": {"content": "{content}", "format": "{format}"},
        },
    },
}


# ---------------------------------------------------------------------------
# MCP JSON-RPC handler
# ---------------------------------------------------------------------------

def _make_trace_id() -> str:
    return str(uuid.uuid4())


async def _call_saimon(
    tool_name: str, arguments: dict[str, Any],
) -> dict[str, Any]:
    """Proxy a tool call to the appropriate Saimon MCP."""
    tool = TOOL_REGISTRY[tool_name]
    url = _build_url(tool["service"], tool["path"])

    # Build body from template, substituting arguments.
    # Drop template placeholders that weren't filled in (e.g. "{criteria}")
    # so the server doesn't receive literal placeholder strings.
    body = json.loads(json.dumps(tool["body_template"]))
    if "parameters" in body:
        for key in list(body["parameters"].keys()):
            value = body["parameters"][key]
            if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                param_name = value[1:-1]
                if param_name in arguments:
                    body["parameters"][key] = arguments[param_name]
                else:
                    del body["parameters"][key]
    body["trace_id"] = _make_trace_id()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Each MCP has its own API key; fall back to default
        svc_key = os.environ.get(
            f"SAIMON_{tool['service'].upper()}_KEY", API_KEY,
        )
        resp = await client.request(
            method=tool["method"],
            url=url,
            json=body,
            headers={"X-Saimon-API-Key": svc_key},
        )
        resp.raise_for_status()
        return resp.json()


def _format_result(data: dict[str, Any]) -> str:
    """Format Saimon response into readable text."""
    status = data.get("status", "unknown")
    payload = data.get("data") or {}
    # Guard: payload may be a non-dict truthy value (e.g. string, list)
    if not isinstance(payload, dict):
        payload = {}

    if "results" in payload:
        # Search result
        results = payload.get("results", [])
        total = payload.get("total_results", len(results))
        lines = [f"Found {len(results)} results "
                 f"(total available: {total}) "
                 f"for '{payload.get('query', '')}':"]
        if not results:
            lines.append("  (no results in this response)")
            return "\n".join(lines)
        lines.append("")
        for i, r in enumerate(results[:10], 1):
            title = r.get("title", "Unknown")
            source = r.get("source_index_label", r.get("source_index", "?"))
            doi = r.get("doi", "")
            authors = ", ".join(r.get("authors", [])[:3])
            year = r.get("year", "")
            lines.append(
                f"{i}. {title}\n"
                f"   Authors: {authors} | Year: {year} | Source: {source}\n"
                f"   DOI: {doi or 'N/A'}"
            )
        return "\n".join(lines)

    elif "verifications" in payload:
        # Verification result
        lines = [
            f"Overall verdict: {payload.get('overall_verdict', 'unknown')}",
            f"Methods used: {payload.get('methods_used', 0)}\n",
        ]
        for v in payload.get("verifications", []):
            lines.append(
                f"  {v['method']}: {v['verdict']} "
                f"(confidence: {v['confidence']})\n"
                f"  {v['explanation'][:300]}"
            )
            if v.get("evidence_source"):
                lines.append(f"\n  Evidence: {v['evidence_source']}")
            lines.append("")
        return "\n".join(lines)

    elif "source_indexes" in payload:
        # Source list
        lines = ["Available source indexes:"]
        for s in payload["source_indexes"]:
            tier = s.get("tier", "")
            lines.append(
                f"  {s['identifier']} ({s['type']})"
                + (f" [Tier {tier}]" if tier else "")
                + f" — {s.get('label', '')}"
            )
        return "\n".join(lines)

    elif "methods" in payload:
        # Verification methods list
        lines = ["Verification methods:"]
        for m in payload["methods"]:
            lines.append(
                f"  {m['name']}: reliability={m.get('reliability','?')} — "
                f"{m.get('description','')[:100]}"
            )
        return "\n".join(lines)

    elif "content_types" in payload:
        # Content type list
        cts = payload.get("content_types", payload.get("types", []))
        lines = [f"{len(cts)} content types available:"]
        for ct in cts[:20]:
            name = ct.get("name", ct) if isinstance(ct, dict) else ct
            desc = ct.get("description", "") if isinstance(ct, dict) else ""
            lines.append(f"  {name}: {desc[:80]}")
        return "\n".join(lines)

    elif "content" in payload:
        # Generated content
        return payload.get("content", json.dumps(payload, indent=2))

    elif "scores" in payload or "score" in payload or "evaluation" in payload:
        # Evaluation result
        scores = payload.get("scores") or []
        overall = payload.get("overall_score", "N/A")
        lines = [f"Overall score: {overall}", f"Criteria evaluated: {len(scores)}", ""]
        for s in scores:
            lines.append(
                f"  {s.get('criterion', '?' )}: {s.get('score', '?')}"
                f" — {s.get('justification', '')[:120]}"
            )
        return "\n".join(lines)

    elif "items" in payload:
        # Explore/browse result
        items = payload.get("items", [])
        lines = [f"Found {len(items)} items:"]
        if not items:
            lines.append("  (no items found)")
            return "\n".join(lines)
        for item in items[:10]:
            title = item.get("title", "Untitled")
            ctype = item.get("content_type", "?")
            lines.append(f"  [{ctype}] {title}")
        return "\n".join(lines)

    # Fallback: pretty-print the whole response
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# MCP Protocol Loop
# ---------------------------------------------------------------------------

async def main() -> None:
    """Run the MCP JSON-RPC loop over stdin/stdout."""
    # Read from stdin, write to stdout
    reader = sys.stdin
    writer = sys.stdout

    server_info = {
        "name": "saimon-researcher",
        "version": "1.0.0",
    }

    for line in reader:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": server_info,
                    "capabilities": {"tools": {}},
                },
            }

        elif method == "tools/list":
            tools = []
            for name, info in TOOL_REGISTRY.items():
                # Build input schema from body_template parameters
                props = {}
                bt = info.get("body_template", {})
                params = bt.get("parameters", {})
                for key, val in params.items():
                    if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
                        props[key] = {"type": "string", "description": f"The {key}"}
                    elif isinstance(val, bool):
                        props[key] = {"type": "boolean", "description": f"Enable {key}"}
                    elif isinstance(val, str):
                        props[key] = {"type": "string", "description": f"Value for {key}"}
                tools.append({
                    "name": name,
                    "description": info["description"],
                    "inputSchema": {"type": "object", "properties": props},
                })
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools},
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            if tool_name not in TOOL_REGISTRY:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
            else:
                try:
                    data = await _call_saimon(tool_name, arguments)
                    text = _format_result(data)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": text}],
                        },
                    }
                except Exception as exc:
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{
                                "type": "text",
                                "text": f"Error calling {tool_name}: {exc}",
                            }],
                            "isError": True,
                        },
                    }

        elif method == "notifications/initialized":
            continue  # No response needed

        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            }

        writer.write(json.dumps(response) + "\n")
        writer.flush()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
