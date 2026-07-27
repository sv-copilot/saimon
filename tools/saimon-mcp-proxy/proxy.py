#!/usr/bin/env python3
"""saimon_mcp_proxy.py — MCP stdio proxy for Saimon REST endpoints.

Makes Saimon's search, verify, and generate MCPs available as native
MCP tools to VS Code agents. Reads JSON-RPC from stdin, proxies to
Saimon HTTP endpoints, writes JSON-RPC to stdout.

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

BASE_URL = os.environ.get(
    "SAIMON_BASE_URL",
    "http://127.0.0.1:8001",  # local dev default: search-mcp directly
)
API_KEY = os.environ.get("SAIMON_API_KEY", "sk-test-search-key")

# Map tool names to (method, path) on the Saimon REST API
TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "saimon_search_scholarly": {
        "description": (
            "Search shadow library sources (Anna's Archive, LibGen, Sci-Hub, "
            "Internet Archive, Academic Torrents) for academic papers, books, "
            "and datasets. Returns ranked results with DOIs, titles, authors, "
            "years, and source attribution. Use this to find academic sources "
            "on any research topic."
        ),
        "method": "POST",
        "path": "/search/tools/search_shadow_libraries",
        "direct_path": "/tools/search_shadow_libraries",
        "body_template": {
            "content_type": "search",
            "parameters": {"query": "{query}", "limit": "{limit}"},
        },
    },
    "saimon_verify_claim": {
        "description": (
            "Verify a factual claim using multiple corroboration methods "
            "(source corroboration, logical consistency, authority check, "
            "temporal validity, shadow source corroboration). Searches "
            "shadow libraries for evidence, then uses DeepSeek LLM to "
            "analyze the claim against found sources. Returns a verdict "
            "(supported/refuted/inconclusive) with confidence scores "
            "and evidence citations."
        ),
        "method": "POST",
        "path": "/verify/tools/verify_claim",
        "direct_path": "/tools/verify_claim",
        "body_template": {
            "content_type": "verify",
            "parameters": {
                "claim": "{claim}",
                "use_shadow_sources": True,
            },
        },
    },
    "saimon_list_sources": {
        "description": (
            "List all available source indexes including knowledge graph "
            "and shadow library sources (Anna's Archive, LibGen, Sci-Hub, "
            "Internet Archive, Academic Torrents). Shows tier and status "
            "for each source."
        ),
        "method": "POST",
        "path": "/search/tools/list_source_indexes",
        "direct_path": "/tools/list_source_indexes",
        "body_template": {"content_type": "search"},
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
    """Proxy a tool call to the Saimon REST API."""
    tool = TOOL_REGISTRY[tool_name]
    # Use Caddy path if base URL contains /saimon, else direct MCP port
    if "/saimon" in BASE_URL:
        path = tool["path"]
    else:
        path = tool.get("direct_path", tool["path"])
    url = f"{BASE_URL}{path}"

    # Build body from template, substituting arguments
    body = json.loads(json.dumps(tool["body_template"]))
    if "parameters" in body:
        for key, value in body["parameters"].items():
            if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                param_name = value[1:-1]
                body["parameters"][key] = arguments.get(
                    param_name, body["parameters"][key],
                )
    body["trace_id"] = _make_trace_id()

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method=tool["method"],
            url=url,
            json=body,
            headers={"X-Saimon-API-Key": API_KEY},
        )
        resp.raise_for_status()
        return resp.json()


def _format_result(data: dict[str, Any]) -> str:
    """Format Saimon response into readable text."""
    status = data.get("status", "unknown")
    payload = data.get("data", {})

    if "results" in payload:
        # Search result
        lines = [f"Found {payload.get('total_results', 0)} results "
                 f"for '{payload.get('query', '')}':\n"]
        for i, r in enumerate(payload["results"][:10], 1):
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
            f"Claim: {payload.get('verifications', [{}])[0].get('explanation', '')[:100] if False else ''}",
            f"Overall verdict: {payload.get('overall_verdict', 'unknown')}",
            f"Methods used: {payload.get('methods_used', 0)}\n",
        ]
        for v in payload.get("verifications", []):
            lines.append(
                f"  {v['method']}: {v['verdict']} "
                f"(confidence: {v['confidence']})\n"
                f"  {v['explanation'][:200]}"
            )
            if v.get("evidence_source"):
                lines.append(f"  Evidence: {v['evidence_source']}")
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
            tools = [
                {"name": name, "description": info["description"],
                 "inputSchema": {
                     "type": "object",
                     "properties": {
                         k: {"type": "string", "description": f"The {k}"}
                         for k in ["query", "claim", "limit"]
                         if ("{" + k + "}") in str(info.get("body_template", {}))
                     },
                 }}
                for name, info in TOOL_REGISTRY.items()
            ]
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
