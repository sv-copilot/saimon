"""auto_seed_loop.py — the gap → seed → verify auto-fill loop.

SAIMON-AUTO-SEED-LOOP-1.

Closes the gap-fill loop for the knowledge base:

    saimon_list_gaps ─► for each gap:
      INSERT seed_request (content_type, prompt, parameters, status='pending')
      self_seed      → generates content, links result_id → node
      generate_verified → re-verify the new node, annotate claims

The pure loop lives here so it can be unit-tested against a mocked DB and
mocked pipeline callbacks.  The generate-mcp FastAPI endpoint wires the real
``self_seed`` / verification helpers into ``fill_gaps``.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# gap → prompt mapping (declarative)
# ---------------------------------------------------------------------------

#: Declarative per-gap-type prompt templates.  ``build_gap_prompt`` formats
#: them with the resolved target keys (claim_text, content_type, query, ...).
GAP_PROMPT_TEMPLATES: dict[str, str] = {
    "observation_unverified": "research and verify: {claim_text}",
    "observation_low_confidence": (
        "research and verify: {claim_text} (current confidence {confidence})"
    ),
    "content_type_sparse": "generate a {content_type} content item",
    "search_empty": "research: {query}",
    "node_unverified": "research and verify node: {title}",
}

#: Fallback template for unknown gap types.
DEFAULT_GAP_PROMPT_TEMPLATE = "research and fill knowledge gap: {gap_type}"

#: Content type used for seed_requests that fill a verification gap.
DEFAULT_SEED_CONTENT_TYPE = "research_note"


def build_gap_prompt(gap_type: str, target: dict[str, Any] | None = None) -> str:
    """Map a gap record to a ``seed_request`` prompt.

    Uses the declarative template for the gap type, formatting it with the
    resolved target.  Unknown gap types fall back to a type-only prompt.
    """
    template = GAP_PROMPT_TEMPLATES.get(gap_type, DEFAULT_GAP_PROMPT_TEMPLATE)
    target = dict(target or {})
    try:
        return template.format(gap_type=gap_type, **target)
    except (KeyError, IndexError, ValueError):
        # Target lacks a key the template expects — degrade to type-only.
        return f"research and fill knowledge gap: {gap_type}"


# ---------------------------------------------------------------------------
# target resolution (gap type → concrete rows)
# ---------------------------------------------------------------------------

async def _resolve_targets(db_pool: Any, gap_type: str) -> list[dict[str, Any]]:
    """Resolve concrete targets for a gap type from the database.

    Returns a list of target dicts whose keys feed the prompt template.
    """
    if gap_type == "observation_unverified":
        rows = await db_pool.fetch(
            "SELECT claim_text FROM observations "
            "WHERE verification_status = 'unverified' OR verification_status IS NULL"
        )
        return [{"claim_text": r["claim_text"]} for r in rows if r.get("claim_text")]

    if gap_type == "observation_low_confidence":
        rows = await db_pool.fetch(
            "SELECT claim_text, confidence_0_1 FROM observations "
            "WHERE confidence_0_1 < 0.6"
        )
        return [
            {"claim_text": r["claim_text"], "confidence": r.get("confidence_0_1", 0.5)}
            for r in rows
            if r.get("claim_text")
        ]

    if gap_type == "content_type_sparse":
        rows = await db_pool.fetch(
            "SELECT ct.type_name AS content_type FROM content_type_registry ct "
            "LEFT JOIN knowledge_graph_nodes kg ON kg.content_type = ct.type_name "
            "GROUP BY ct.type_name HAVING COUNT(kg.id) <= 1"
        )
        return [{"content_type": r["content_type"]} for r in rows if r.get("content_type")]

    if gap_type == "search_empty":
        rows = await db_pool.fetch(
            "SELECT query FROM shadow_search_log WHERE result_count = 0"
        )
        return [{"query": r["query"]} for r in rows if r.get("query")]

    if gap_type == "node_unverified":
        rows = await db_pool.fetch(
            "SELECT n.title AS title, n.id AS node_id FROM knowledge_graph_nodes n "
            "LEFT JOIN observations o ON o.node_id = n.id WHERE o.id IS NULL"
        )
        return [{"title": r["title"], "node_id": r.get("node_id")} for r in rows if r.get("title")]

    return []


def _content_type_for_gap(gap_type: str, target: dict[str, Any]) -> str:
    """Choose the seed_request content type for a gap target."""
    if gap_type == "content_type_sparse":
        return target.get("content_type") or DEFAULT_SEED_CONTENT_TYPE
    return DEFAULT_SEED_CONTENT_TYPE


def _target_key(gap_type: str, target: dict[str, Any]) -> str:
    """Return a stable, human-readable key for a gap target (for reporting)."""
    if gap_type == "observation_unverified":
        return target.get("claim_text", "")
    if gap_type == "observation_low_confidence":
        return target.get("claim_text", "")
    if gap_type == "content_type_sparse":
        return target.get("content_type", "")
    if gap_type == "search_empty":
        return target.get("query", "")
    if gap_type == "node_unverified":
        return target.get("title", "")
    return json.dumps(target, sort_keys=True, default=str)

# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------

async def fill_gaps(
    gaps: list[dict[str, Any]],
    db_pool: Any | None = None,
    *,
    self_seed_fn: Any | None = None,
    generate_verified_fn: Any | None = None,
) -> dict[str, Any]:
    """Run the gap → seed → verify loop over a set of gap records.

    ``gaps`` uses the same shape as ``saimon_list_gaps`` output
    (``{"type", "severity", "count"}``).  ``self_seed_fn`` is an async
    callable ``(seed_id) -> dict`` returning ``node_id``/``content``/
    ``content_type`` on success.  ``generate_verified_fn`` is an async
    callable ``(node_id, content, content_type) -> dict`` that re-verifies
    already-generated content.

    Returns a report with ``filled``/``failed``/``skipped`` result lists and
    a ``summary`` of counts.  Idempotent: targets that already have a
    pending/complete ``seed_request`` for the same prompt are skipped.
    """
    report: dict[str, Any] = {"filled": [], "failed": [], "skipped": []}

    if db_pool is None:
        report["summary"] = _summary(report)
        return report

    for gap in gaps:
        gap_type = gap.get("type") or gap.get("gap_type")
        if not gap_type:
            continue

        try:
            targets = await _resolve_targets(db_pool, gap_type)
        except Exception as exc:  # noqa: BLE001 — per-gap resilience
            report["failed"].append(
                {
                    "gap_type": gap_type,
                    "target": None,
                    "status": "failed",
                    "error": f"target resolution failed: {exc}",
                }
            )
            continue

        for target in targets:
            prompt = build_gap_prompt(gap_type, target)
            content_type = _content_type_for_gap(gap_type, target)
            params = {"gap_type": gap_type, "target": _target_key(gap_type, target)}

            result = {
                "gap_type": gap_type,
                "target": _target_key(gap_type, target),
            }

            # Dedupe guard — don't re-seed a target that already has a
            # pending or complete seed_request with the same prompt.
            try:
                existing = await db_pool.fetchval(
                    "SELECT 1 FROM seed_requests "
                    "WHERE prompt = $1 AND status IN ('pending', 'complete') LIMIT 1",
                    prompt,
                )
            except Exception as exc:  # noqa: BLE001
                report["failed"].append(
                    {**result, "status": "failed", "error": f"dedupe check failed: {exc}"}
                )
                continue

            if existing:
                report["skipped"].append(
                    {**result, "status": "skipped", "reason": "already_pending_or_complete"}
                )
                continue

            # Create the pending seed_request.
            try:
                seed_id = await db_pool.fetchval(
                    "INSERT INTO seed_requests "
                    "(content_type, prompt, parameters, status) "
                    "VALUES ($1, $2, $3::jsonb, 'pending') RETURNING id",
                    content_type,
                    prompt,
                    json.dumps(params),
                )
            except Exception as exc:  # noqa: BLE001
                report["failed"].append(
                    {**result, "status": "failed", "error": f"seed insert failed: {exc}"}
                )
                continue

            if seed_id is None:
                report["failed"].append(
                    {**result, "status": "failed", "error": "seed insert returned no id"}
                )
                continue

            result["seed_id"] = seed_id


            # Generate + persist content via self_seed.
            if self_seed_fn is None:
                report["filled"].append({**result, "node_id": None, "status": "filled"})
                continue

            try:
                seed_result = await self_seed_fn(seed_id)
            except Exception as exc:  # noqa: BLE001
                report["failed"].append(
                    {**result, "status": "failed", "error": f"self_seed failed: {exc}"}
                )
                continue

            if not isinstance(seed_result, dict):
                seed_result = {}

            if seed_result.get("status") == "failed":
                report["failed"].append(
                    {
                        **result,
                        "status": "failed",
                        "error": seed_result.get("error", "self_seed failed"),
                    }
                )
                continue

            node_id = seed_result.get("node_id")
            content = seed_result.get("content")
            node_content_type = seed_result.get("content_type") or content_type
            result["node_id"] = node_id

            if not node_id:
                report["failed"].append(
                    {**result, "status": "failed", "error": "self_seed produced no node"}
                )
                continue

            # Re-verify the new node.
            if generate_verified_fn is not None and content:
                try:
                    await generate_verified_fn(node_id, content, node_content_type)
                except Exception as exc:  # noqa: BLE001
                    report["failed"].append(
                        {**result, "status": "failed", "error": f"verify failed: {exc}"}
                    )
                    continue

            report["filled"].append({**result, "status": "filled"})

    report["summary"] = _summary(report)
    return report


def _summary(report: dict[str, Any]) -> dict[str, int]:
    return {
        "filled": len(report["filled"]),
        "failed": len(report["failed"]),
        "skipped": len(report["skipped"]),
        "total": len(report["filled"]) + len(report["failed"]) + len(report["skipped"]),
    }

