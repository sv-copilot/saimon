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
            "parameters": {
                "claim": "{claim}",
                "use_shadow_sources": True,
                "adversarial": "{adversarial}",
                "risk_profile": "{risk_profile}",
                "verify_citations": "{verify_citations}",
            },
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

    # ── Verify Tools (continued) ────────────────────────────────
    "saimon_extract_claims": {
        "description": (
            "Extract falsifiable claims from source text with confidence "
            "scores. Returns a list of claims with topics, confidence "
            "ratings, and rationales. Persists claims as observations "
            "in the knowledge graph when DB is available."
        ),
        "service": "verify",
        "method": "POST",
        "path": "/tools/extract_claims",
        "body_template": {
            "content_type": "extract",
            "parameters": {"source_text": "{source_text}", "max_claims": "{max_claims}"},
        },
    },

    # ── Evaluate Tools ──────────────────────────────────────────
    "saimon_evaluate_content": {
        "description": (
            "Score generated content against quality criteria (clarity, "
            "completeness, coherence, conciseness, tone_match, ai_detection). "
            "Returns scored results with per-criterion breakdown. "
            "The ai_detection criterion uses 12 deterministic heuristic "
            "checks (template phrases, hedging, adjective inflation, "
            "burstiness, perplexity proxy, corporate neutrality, etc.) "
            "— not an ML classifier."
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

    # ── Composite Pipeline Tools ────────────────────────────────
    "saimon_generate_verified": {
        "description": (
            "Generate research content AND verify all factual claims in "
            "a single call. Chains: generate → [ai_detection] → extract "
            "claims → verify each claim → annotate. Each claim is "
            "verified with adversarial checking, risk_profile=high, and "
            "citation verification. Returns annotated content with "
            "[VERIFIED ✓] / [UNVERIFIED ⚠ reason] markers, a "
            "verification summary, ai_detection score (optional), "
            "evidence links, and a list of degraded steps."
        ),
        "service": "generate",  # primary service for URL routing
        "method": "POST",
        "path": "/tools/generate_content",  # placeholder — handled by pipeline
        "body_template": {
            "content_type": "{content_type}",
            "parameters": {
                "prompt": "{prompt}",
                "tone": "{tone}",
                "sources": "{sources}",
                "auto_search": "{auto_search}",
                "ai_detection": "{ai_detection}",
                "cross_check": "{cross_check}",
            },
        },
        "composite": True,  # marker: routed to _run_generate_verified_pipeline
    },
    "saimon_audit_content": {
        "description": (
            "Audit existing text for AI fingerprints and factual reliability. "
            "Chains: ai_detection → extract claims → verify each claim → "
            "audit report. No generation step. Returns AI detection score "
            "with flags, claim-by-claim verification results, evidence links, "
            "and a human-readable summary."
        ),
        "service": "evaluate",  # primary service for URL routing
        "method": "POST",
        "path": "/tools/evaluate_content",  # placeholder — handled by pipeline
        "body_template": {
            "content_type": "audit",
            "parameters": {"content": "{content}"},
        },
        "composite": True,
        "pipeline": "audit_content",
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


async def _auto_search_sources(
    prompt: str, limit: int = 5,
) -> list[dict[str, Any]]:
    """Call saimon_search_scholarly and map results to SourceReference dicts.

    Raises on network/auth errors so the caller can record degraded steps.
    Returns empty list when search succeeds but finds no results.
    """
    search_resp = await _call_saimon("saimon_search_scholarly", {
        "query": prompt,
        "limit": limit,
    })

    results = (search_resp.get("data") or {}).get("results") or []
    if not isinstance(results, list):
        return []

    sources: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        sources.append({
            "type": r.get("type", "academic_paper"),
            "identifier": r.get("doi") or r.get("title", "unknown"),
            "relevance_score": r.get("relevance_score"),
        })
    return sources


async def _run_generate_verified_pipeline(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Composite pipeline: generate → evaluate → extract → verify → annotate.

    Each step is wrapped in try/except for graceful degradation.
    Returns a dict with keys:
      - content (str): annotated generated content
      - verification_summary (dict): per-claim verdicts
      - ai_detection_score (dict | None): optional AI detection results
      - evidence_links (list): citation evidence links
      - degraded_steps (list[str]): steps that failed gracefully
    """
    degraded: list[str] = []
    result: dict[str, Any] = {}

    # ── Step 1: Generate content ────────────────────────────────
    prompt = arguments.get("prompt", "")
    content_type = arguments.get("content_type", "research_note")
    tone = arguments.get("tone", "neutral")
    sources = arguments.get("sources", [])

    # ── Step 0: Optional auto-search for sources ─────────────────
    auto_search = arguments.get("auto_search", False)
    if isinstance(auto_search, str):
        auto_search = auto_search.lower() in ("true", "1", "yes")

    if auto_search and prompt:
        try:
            discovered = await _auto_search_sources(prompt)
            if discovered:
                existing_ids: set[str] = {
                    s.get("identifier") if isinstance(s, dict) else str(s)
                    for s in (sources if isinstance(sources, list) else [])
                }
                for d in discovered:
                    if d.get("identifier") not in existing_ids:
                        if isinstance(sources, list):
                            sources.append(d)
                        else:
                            sources = [d]
                        existing_ids.add(d.get("identifier", ""))
        except Exception as exc:
            degraded.append(f"auto_search: {exc}")

    gen_args: dict[str, Any] = {
        "prompt": prompt,
        "content_type": content_type,
        "tone": tone,
    }
    if sources:
        gen_args["sources"] = sources

    content: str = ""
    try:
        gen_resp = await _call_saimon("saimon_generate_content", gen_args)
        gen_data = gen_resp.get("data", {})
        if isinstance(gen_data, dict):
            content = gen_data.get("content", str(gen_data))
        else:
            content = str(gen_data)
    except Exception as exc:
        degraded.append(f"generate: {exc}")
        return {
            "status": "error",
            "errors": [f"Generate step failed: {exc}"],
            "degraded_steps": degraded,
        }

    # ── Step 2: Optional AI detection ───────────────────────────
    ai_detection_score: dict[str, Any] | None = None
    ai_detection_enabled = arguments.get("ai_detection", False)
    # Accept string "true"/"false" from MCP argument serialization
    if isinstance(ai_detection_enabled, str):
        ai_detection_enabled = ai_detection_enabled.lower() in ("true", "1", "yes")

    if ai_detection_enabled:
        try:
            eval_resp = await _call_saimon("saimon_evaluate_content", {
                "content": content,
                "criteria": "ai_detection",
            })
            eval_data = eval_resp.get("data", {})
            if isinstance(eval_data, dict):
                scores = eval_data.get("scores", [])
                overall = eval_data.get(
                    "overall_score",
                    sum(s.get("score", 0) for s in scores) / max(len(scores), 1) if scores else None,
                )
                ai_detection_score = {
                    "scores": scores,
                    "overall_score": overall,
                }
        except Exception as exc:
            degraded.append(f"ai_detection: {exc}")

    # ── Step 3: Extract claims ──────────────────────────────────
    claims: list[dict[str, Any]] = []
    try:
        claims_resp = await _call_saimon("saimon_extract_claims", {
            "source_text": content,
        })
        claims_data = claims_resp.get("data", {})
        if isinstance(claims_data, dict):
            claims = claims_data.get("claims", [])
    except Exception as exc:
        degraded.append(f"extract_claims: {exc}")
        claims = []

    # ── Step 4: Verify each claim ───────────────────────────────
    cross_check = arguments.get("cross_check", False)
    if isinstance(cross_check, str):
        cross_check = cross_check.lower() in ("true", "1", "yes")

    verified_claims: list[dict[str, Any]] = []
    all_evidence_links: list[dict[str, Any]] = []
    for i, claim in enumerate(claims):
        claim_text = claim.get("claim_text", str(claim)) if isinstance(claim, dict) else str(claim)
        try:
            verify_args: dict[str, Any] = {
                "claim": claim_text,
                "adversarial": True,
                "risk_profile": "high",
                "verify_citations": True,
                "use_shadow_sources": True,
            }
            verify_resp = await _call_saimon("saimon_verify_claim", verify_args)
            verify_data = verify_resp.get("data", {})
            if isinstance(verify_data, dict):
                overall_v = verify_data.get("overall_verdict", "inconclusive")
                confidence_v = verify_data.get("overall_confidence", 0.0)
                abstained = verify_data.get("abstained", False)
                dispute = verify_data.get("adversarial", {})
                links = verify_data.get("evidence_links", [])

                claim_result: dict[str, Any] = {
                    "claim_text": claim_text,
                    "claim_index": i,
                    "verdict": overall_v,
                    "confidence": confidence_v,
                    "abstained": abstained,
                }
                if isinstance(dispute, dict) and dispute.get("disputed"):
                    claim_result["disputed"] = True
                    claim_result["adversarial_perspective"] = dispute.get(
                        "adversarial_perspective", ""
                    )

                verified_claims.append(claim_result)
                all_evidence_links.extend(links)
        except Exception as exc:
            degraded.append(f"verify_claim[{i}]: {exc}")
            verified_claims.append({
                "claim_text": claim_text,
                "claim_index": i,
                "verdict": "error",
                "confidence": 0.0,
                "error": str(exc),
            })

    # ── Step 4b: Optional cross-check (second verify pass) ──────
    if cross_check:
        for i, claim in enumerate(claims):
            claim_text = claim.get("claim_text", str(claim)) if isinstance(claim, dict) else str(claim)
            try:
                verify_args_2: dict[str, Any] = {
                    "claim": claim_text,
                    "adversarial": True,
                    "risk_profile": "high",
                    "verify_citations": True,
                    "use_shadow_sources": True,
                }
                verify_resp_2 = await _call_saimon("saimon_verify_claim", verify_args_2)
                verify_data_2 = verify_resp_2.get("data", {})
                if isinstance(verify_data_2, dict):
                    cross_verdict = verify_data_2.get("overall_verdict", "inconclusive")
                    # Compare with first pass
                    first = verified_claims[i] if i < len(verified_claims) else {}
                    first_verdict = first.get("verdict", "unknown")
                    if cross_verdict != first_verdict:
                        verified_claims[i]["cross_check_disagreement"] = True
                        verified_claims[i]["cross_check_verdict"] = cross_verdict
                    else:
                        verified_claims[i]["cross_check_agreement"] = True
            except Exception as exc:
                degraded.append(f"cross_check[{i}]: {exc}")

    # ── Step 5: Annotate content ────────────────────────────────
    annotated = content
    for vc in verified_claims:
        claim_text = vc.get("claim_text", "")
        verdict = vc.get("verdict", "inconclusive")
        if verdict == "error":
            marker = f"[UNVERIFIED ⚠ verification error]"
        elif verdict == "supported":
            marker = "[VERIFIED ✓]"
        elif verdict == "refuted":
            marker = f"[UNVERIFIED ⚠ refuted]"
        elif verdict == "inconclusive":
            marker = f"[UNVERIFIED ⚠ inconclusive]"
        else:
            marker = f"[UNVERIFIED ⚠ {verdict}]"

        # Insert marker near the claim text if found in content
        if claim_text and claim_text in annotated:
            annotated = annotated.replace(
                claim_text, f"{marker} {claim_text}", 1
            )

    # ── Step 6: Build verification summary ──────────────────────
    total = len(verified_claims)
    supported = sum(1 for vc in verified_claims if vc.get("verdict") == "supported")
    refuted = sum(1 for vc in verified_claims if vc.get("verdict") == "refuted")
    inconclusive = sum(1 for vc in verified_claims if vc.get("verdict") == "inconclusive")
    errors = sum(1 for vc in verified_claims if vc.get("verdict") == "error")
    disputed = sum(1 for vc in verified_claims if vc.get("disputed"))

    verification_summary: dict[str, Any] = {
        "total_claims": total,
        "supported": supported,
        "refuted": refuted,
        "inconclusive": inconclusive,
        "errors": errors,
        "disputed": disputed,
        "verified_claims": verified_claims,
    }

    if cross_check:
        cross_agreements = sum(
            1 for vc in verified_claims if vc.get("cross_check_agreement")
        )
        cross_disagreements = sum(
            1 for vc in verified_claims if vc.get("cross_check_disagreement")
        )
        verification_summary["cross_check"] = {
            "agreements": cross_agreements,
            "disagreements": cross_disagreements,
        }

    result = {
        "status": "degraded" if degraded else "success",
        "content": annotated,
        "verification_summary": verification_summary,
        "ai_detection_score": ai_detection_score,
        "evidence_links": all_evidence_links,
        "degraded_steps": degraded if degraded else None,
    }

    return result


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


def _format_composite_result(data: dict[str, Any]) -> str:
    """Format the generate_verified composite result into readable text."""
    status = data.get("status", "unknown")
    content = data.get("content", "")
    degraded = data.get("degraded_steps") or []
    vs = data.get("verification_summary", {})
    ai_score = data.get("ai_detection_score")
    evidence_links = data.get("evidence_links") or []

    lines = [
        f"Status: {status}",
        "",
    ]

    if degraded:
        lines.append(f"⚠ Degraded steps ({len(degraded)}):")
        for d in degraded:
            lines.append(f"  - {d}")
        lines.append("")

    if ai_score is not None:
        overall = ai_score.get("overall_score", "N/A")
        lines.append(f"AI Detection Score: {overall}")
        scores = ai_score.get("scores", [])
        for s in scores:
            lines.append(
                f"  {s.get('criterion', '?')}: {s.get('score', '?')}"
                f" — {s.get('justification', '')[:120]}"
            )
        lines.append("")

    # Verification summary
    lines.append("── Verification Summary ──")
    lines.append(f"Claims found: {vs.get('total_claims', 0)}")
    lines.append(f"  ✓ Supported:   {vs.get('supported', 0)}")
    lines.append(f"  ✗ Refuted:     {vs.get('refuted', 0)}")
    lines.append(f"  ? Inconclusive:{vs.get('inconclusive', 0)}")
    lines.append(f"  ⚠ Errors:      {vs.get('errors', 0)}")
    if vs.get("disputed"):
        lines.append(f"  ⚡ Disputed:    {vs.get('disputed', 0)}")

    cross = vs.get("cross_check")
    if cross:
        lines.append(f"\nCross-check: {cross.get('agreements', 0)} agreements, "
                      f"{cross.get('disagreements', 0)} disagreements")

    # Per-claim details
    verified_claims = vs.get("verified_claims", [])
    if verified_claims:
        lines.append("\n── Claim Verdicts ──")
        for vc in verified_claims:
            idx = vc.get("claim_index", "?")
            verdict = vc.get("verdict", "?")
            conf = vc.get("confidence", 0.0)
            claim_preview = vc.get("claim_text", "")[:80]
            marker = ("✓" if verdict == "supported"
                      else "✗" if verdict == "refuted"
                      else "?" if verdict == "inconclusive"
                      else "⚠")
            lines.append(f"  [{idx}] {marker} ({conf:.2f}) {claim_preview}")
            if vc.get("disputed"):
                lines.append(f"       ⚡ Adversarial disagrees: {vc.get('adversarial_perspective', '')}")

    if evidence_links:
        lines.append(f"\n── Evidence Links ({len(evidence_links)}) ──")
        for el in evidence_links[:10]:
            si = el.get("source_identifier", "?")
            conf = el.get("confidence", 0.0)
            flagged = " ⚠ FLAGGED" if el.get("flagged") else ""
            lines.append(f"  {si} (conf={conf:.2f}){flagged}")

    lines.append("")
    lines.append("── Annotated Content ──")
    lines.append(content)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audit Content Composite Pipeline (PIPELINE-AUDIT-1)
# ---------------------------------------------------------------------------

async def _run_audit_pipeline(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Composite pipeline: ai_detection → extract claims → verify → report.

    Takes existing text (no generation). Returns audit report with
    AI detection score, claim-by-claim verification, and summary.
    """
    degraded: list[str] = []
    content = arguments.get("content", "")

    if not content or not content.strip():
        return {
            "status": "error",
            "errors": ["No content provided for audit"],
            "degraded_steps": [],
        }

    # ── Step 1: AI detection ────────────────────────────────────
    ai_detection_score: dict[str, Any] | None = None
    try:
        eval_resp = await _call_saimon("saimon_evaluate_content", {
            "content": content,
            "criteria": "ai_detection",
        })
        eval_data = eval_resp.get("data", {})
        if isinstance(eval_data, dict):
            scores = eval_data.get("scores", [])
            overall = eval_data.get(
                "overall_score",
                sum(s.get("score", 0) for s in scores) / max(len(scores), 1)
                if scores else None,
            )
            flags = eval_data.get("flags", [])
            ai_detection_score = {
                "scores": scores,
                "overall_score": overall,
                "flags": flags,
            }
    except Exception as exc:
        degraded.append(f"ai_detection: {exc}")

    # ── Step 2: Extract claims ──────────────────────────────────
    claims: list[dict[str, Any]] = []
    try:
        claims_resp = await _call_saimon("saimon_extract_claims", {
            "source_text": content,
        })
        claims_data = claims_resp.get("data", {})
        if isinstance(claims_data, dict):
            claims = claims_data.get("claims", [])
    except Exception as exc:
        degraded.append(f"extract_claims: {exc}")

    # ── Step 3: Verify each claim (up to 10) ────────────────────
    verified_claims: list[dict[str, Any]] = []
    all_evidence_links: list[dict[str, Any]] = []
    for i, claim in enumerate(claims[:10]):
        claim_text = (
            claim.get("claim_text", str(claim))
            if isinstance(claim, dict) else str(claim)
        )
        try:
            verify_args: dict[str, Any] = {
                "claim": claim_text,
                "adversarial": True,
                "risk_profile": "high",
                "verify_citations": True,
                "use_shadow_sources": True,
            }
            verify_resp = await _call_saimon("saimon_verify_claim", verify_args)
            verify_data = verify_resp.get("data", {})
            if isinstance(verify_data, dict):
                verified_claims.append({
                    "claim_text": claim_text,
                    "claim_index": i,
                    "verdict": verify_data.get("overall_verdict", "inconclusive"),
                    "confidence": verify_data.get("overall_confidence", 0.0),
                    "abstained": verify_data.get("abstained", False),
                    "methods": verify_data.get("verifications", []),
                })
                links = verify_data.get("evidence_links", [])
                all_evidence_links.extend(links)
        except Exception as exc:
            degraded.append(f"verify_claim[{i}]: {exc}")
            verified_claims.append({
                "claim_text": claim_text,
                "claim_index": i,
                "verdict": "error",
                "confidence": 0.0,
                "error": str(exc),
            })

    # ── Step 4: Build audit report ──────────────────────────────
    total = len(verified_claims)
    supported = sum(1 for vc in verified_claims if vc.get("verdict") == "supported")
    refuted = sum(1 for vc in verified_claims if vc.get("verdict") == "refuted")
    inconclusive = sum(1 for vc in verified_claims if vc.get("verdict") == "inconclusive")
    errors = sum(1 for vc in verified_claims if vc.get("verdict") == "error")

    return {
        "status": "degraded" if degraded else "success",
        "ai_detection": ai_detection_score,
        "claims": {
            "total": len(claims),
            "verified": total - errors,
            "unverified": inconclusive,
            "disputed": refuted,
        },
        "verifications": verified_claims,
        "evidence_links": all_evidence_links,
        "summary": (
            f"{len(claims)} claims extracted. "
            f"{supported} supported, {refuted} refuted, "
            f"{inconclusive} inconclusive, {errors} errors."
        ),
        "degraded_steps": degraded if degraded else None,
    }


def _format_audit_result(data: dict[str, Any]) -> str:
    """Format the audit_content composite result into readable text."""
    lines: list[str] = []

    status = data.get("status", "unknown")
    lines.append(f"Audit Status: {status.upper()}")
    lines.append("=" * 60)

    # ── AI Detection ─────────────────────────────────────────────
    ai = data.get("ai_detection")
    if ai and ai.get("overall_score") is not None:
        score = ai["overall_score"]
        risk = "LIKELY AI-GENERATED" if score < 0.3 else (
            "POSSIBLY AI-ASSISTED" if score < 0.5 else "LIKELY HUMAN"
        )
        lines.append(f"\nAI Detection Score: {score:.2f} ({risk})")
        flags = ai.get("flags", [])
        if flags:
            lines.append("  Flags: " + ", ".join(str(f) for f in flags))
        # Per-criterion details
        for s in ai.get("scores", []):
            lines.append(f"  {s.get('criterion', '?'):20s}: {s.get('score', 0):.2f}")
    else:
        lines.append("\nAI Detection: not available")

    # ── Claims Summary ───────────────────────────────────────────
    claims = data.get("claims", {})
    lines.append(f"\n── Claims ──")
    lines.append(f"  Total: {claims.get('total', 0)}")
    lines.append(f"  Verified: {claims.get('verified', 0)}")
    lines.append(f"  Unverified: {claims.get('unverified', 0)}")
    lines.append(f"  Disputed: {claims.get('disputed', 0)}")

    # ── Per-Claim Verdicts ───────────────────────────────────────
    verifications = data.get("verifications", [])
    if verifications:
        lines.append(f"\n── Claim-by-Claim Results ({len(verifications)}) ──")
        for vc in verifications:
            verdict = vc.get("verdict", "?")
            icon = {
                "supported": "✅",
                "refuted": "❌",
                "inconclusive": "⚠️",
                "error": "💥",
            }.get(verdict, "❓")
            conf = vc.get("confidence", 0)
            lines.append(
                f"  {icon} [{verdict.upper():12s}] (conf={conf:.2f}) "
                f"{vc.get('claim_text', '')[:100]}"
            )

    # ── Evidence Links ───────────────────────────────────────────
    evidence = data.get("evidence_links", [])
    if evidence:
        lines.append(f"\n── Evidence Links ({len(evidence)}) ──")
        for el in evidence[:10]:
            si = el.get("source_identifier", "?")
            conf = el.get("confidence", 0.0)
            lines.append(f"  {si} (conf={conf:.2f})")

    # ── Summary ──────────────────────────────────────────────────
    lines.append(f"\n── Summary ──")
    lines.append(data.get("summary", "No summary available"))

    # ── Degraded ─────────────────────────────────────────────────
    degraded = data.get("degraded_steps")
    if degraded:
        lines.append(f"\n── Degraded Steps ──")
        for d in degraded:
            lines.append(f"  ⚠ {d}")

    return "\n".join(lines)


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
            elif TOOL_REGISTRY[tool_name].get("composite"):
                # Composite tool — dispatched by pipeline name
                pipeline_name = TOOL_REGISTRY[tool_name].get(
                    "pipeline", "generate_verified"
                )
                pipelines: dict[str, tuple[Any, Any]] = {
                    "generate_verified": (
                        _run_generate_verified_pipeline,
                        _format_composite_result,
                    ),
                    "audit_content": (
                        _run_audit_pipeline,
                        _format_audit_result,
                    ),
                }
                try:
                    pipeline_fn, format_fn = pipelines.get(
                        pipeline_name,
                        (_run_generate_verified_pipeline, _format_composite_result),
                    )
                    data = await pipeline_fn(arguments)
                    text = format_fn(data)
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
                                "text": f"Error in {pipeline_name} pipeline: {exc}",
                            }],
                            "isError": True,
                        },
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
