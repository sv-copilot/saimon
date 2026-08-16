"""citations.py — citation edge + case node conventions over the KG.

Legal citations are directed ``knowledge_graph_edges`` with a namespaced
``relation_type`` of ``legal.cites``.  Case nodes are ``knowledge_graph_nodes``
with ``content_type = 'legal:case'``.  All domain data lives in ``metadata``
JSONB — no core schema changes.
"""

from __future__ import annotations

from typing import Any

CITES_RELATION_TYPE = "legal.cites"
LEGAL_CASE_CONTENT_TYPE = "legal:case"


def build_citation_edge(
    source_id: str,
    target_id: str,
    *,
    weight: float = 1.0,
    position: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a citation edge payload for ``knowledge_graph_edges``.

    ``relation_type`` is fixed to ``legal.cites``; weight, position, and any
    extra domain data live in ``metadata`` JSONB.
    """
    metadata: dict[str, Any] = {}
    if position is not None:
        metadata["position"] = position
    if extra:
        metadata.update(extra)
    return {
        "source_id": source_id,
        "target_id": target_id,
        "relation_type": CITES_RELATION_TYPE,
        "weight": weight,
        "metadata": metadata,
    }


def is_citation_edge(edge: dict[str, Any]) -> bool:
    """True when *edge* uses the ``legal.cites`` relation type."""
    return edge.get("relation_type") == CITES_RELATION_TYPE


def build_case_node(
    node_id: str,
    *,
    citation_string: str | None = None,
    court: str | None = None,
    jurisdiction: str | None = None,
    decided_date: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a legal case node payload; domain data lives in metadata JSONB."""
    metadata: dict[str, Any] = {}
    for key, value in (
        ("citation_string", citation_string),
        ("court", court),
        ("jurisdiction", jurisdiction),
        ("decided_date", decided_date),
    ):
        if value is not None:
            metadata[key] = value
    if extra:
        metadata.update(extra)
    return {
        "id": node_id,
        "content_type": LEGAL_CASE_CONTENT_TYPE,
        "metadata": metadata,
    }
