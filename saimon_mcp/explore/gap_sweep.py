"""
Gap detection for the knowledge base.

Computes on-the-fly gaps across five signals:
  1. content_type_sparse       — content types with <= `sparse_threshold` nodes
  2. observation_unverified    — observations unverified or missing verification
  3. observation_low_confidence— observations with confidence_0_1 < 0.6
  4. search_empty              — shadow searches that returned zero results
  5. node_unverified           — knowledge graph nodes with no linked observation

All queries run against the database pool passed in. The function returns a
`list[dict]`; an empty list means no gaps found (never an error).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Severity per gap type — kept in one place so the MCP tool / proxy can reuse it.
GAP_SEVERITIES = {
    "content_type_sparse": "low",
    "observation_unverified": "medium",
    "observation_low_confidence": "medium",
    "search_empty": "high",
    "node_unverified": "medium",
}

# Threshold for deciding a content type is "sparse" (0 or few nodes).
DEFAULT_SPARSE_THRESHOLD = 1


async def list_gaps(
    db_pool: Any | None = None,
    sparse_threshold: int = DEFAULT_SPARSE_THRESHOLD,
) -> list[dict[str, Any]]:
    """
    Sweep the KG and return a list of gap dictionaries.

    Each entry has:
        type     : str   — one of the five gap type names
        severity : str   — low | medium | high
        count    : int   — how many records/items fall into the gap

    If `db_pool` is None or no gaps are found, returns [].
    """
    if db_pool is None:
        return []

    gaps: list[dict[str, Any]] = []

    try:
        async with db_pool.acquire() as conn:
            # 1. content_type_sparse: types in content_type_registry with ≤ sparse_threshold nodes
            sparse_rows = await conn.fetch(
                """
                SELECT ct.type_name, COUNT(kg.id) AS node_count
                FROM content_type_registry ct
                LEFT JOIN knowledge_graph_nodes kg
                  ON kg.content_type = ct.type_name
                GROUP BY ct.type_name
                HAVING COUNT(kg.id) <= $1
                """,
                sparse_threshold,
            )
            if sparse_rows:
                gaps.append({
                    "type": "content_type_sparse",
                    "severity": GAP_SEVERITIES["content_type_sparse"],
                    "count": len(sparse_rows),
                })

            # 2. observation_unverified: unverified or NULL verification_status
            unverified_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM observations
                WHERE verification_status = 'unverified'
                   OR verification_status IS NULL
                """
            )
            if unverified_count:
                gaps.append({
                    "type": "observation_unverified",
                    "severity": GAP_SEVERITIES["observation_unverified"],
                    "count": int(unverified_count),
                })

            # 3. observation_low_confidence: confidence_0_1 < 0.6
            low_confidence_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM observations
                WHERE confidence_0_1 < 0.6
                """
            )
            if low_confidence_count:
                gaps.append({
                    "type": "observation_low_confidence",
                    "severity": GAP_SEVERITIES["observation_low_confidence"],
                    "count": int(low_confidence_count),
                })

            # 4. search_empty: shadow search queries that returned zero results.
            #    The table name follows the convention used by the shadow search cache.
            try:
                empty_search_count = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM shadow_search_log
                    WHERE result_count = 0
                    """
                )
                if empty_search_count:
                    gaps.append({
                        "type": "search_empty",
                        "severity": GAP_SEVERITIES["search_empty"],
                        "count": int(empty_search_count),
                    })
            except Exception as e:
                # The shadow search log table may not exist in some deployments.
                # Log and continue — this gap is optional in the first pass.
                logger.debug("shadow_search_log query skipped: %s", e)

            # 5. node_unverified: KG nodes with no linked observation
            unverified_nodes_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM knowledge_graph_nodes n
                LEFT JOIN observations o ON o.node_id = n.id
                WHERE o.id IS NULL
                """
            )
            if unverified_nodes_count:
                gaps.append({
                    "type": "node_unverified",
                    "severity": GAP_SEVERITIES["node_unverified"],
                    "count": int(unverified_nodes_count),
                })
    except Exception:
        logger.exception("gap sweep failed")
        # Preserve the "empty means clean" contract — do not raise.
        return []

    return gaps


async def saimon_list_gaps(db_pool: Any | None = None) -> list[dict[str, Any]]:
    """
    MCP tool handler for `saimon_list_gaps`.

    This thin wrapper exists so the MCP framework can call it with the same
    signature as other explore tools. It simply delegates to `list_gaps`.
    """
    return await list_gaps(db_pool)


# Metadata used by the proxy TOOL_REGISTRY.
TOOL_SPEC = {
    "name": "saimon_list_gaps",
    "description": (
        "List knowledge-base gaps: thin content types, unverified observations, "
        "low-confidence observations, empty shadow searches, and unverified nodes."
    ),
    "parameters": {},
    "handler": saimon_list_gaps,
}
