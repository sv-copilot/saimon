"""Document review state (SAIMON-DOC-REVIEW-STATE-1).

Every document in the corpus currently has equal standing: a form's boilerplate
and a peer-reviewed paper compete on the same vector distance. Review status lets
the operator say what counts as evidence, and lets retrieval honour it.

Stored in ``metadata`` for the same reason as ingest status: ``schema.sql`` only
runs on a fresh database, so a new column would be absent on the live cluster
when the code that reads it deploys.
"""

from __future__ import annotations

import json
from typing import Any

REVIEW_KEY = "review_status"

PENDING = "pending"
ACCEPTED_RESEARCH = "accepted_research"
GENERAL_CONTEXT = "general_context"
NEEDS_CLARIFICATION = "needs_user_clarification"
REJECTED = "rejected"

ALL_REVIEW_STATUSES = (
    PENDING,
    ACCEPTED_RESEARCH,
    GENERAL_CONTEXT,
    NEEDS_CLARIFICATION,
    REJECTED,
)

DEFAULT_REVIEW_STATUS = ACCEPTED_RESEARCH


def normalise_review_statuses(values: Any) -> list[str]:
    """Validate a caller-supplied filter list; reject unknown values loudly."""
    if values is None:
        return [DEFAULT_REVIEW_STATUS]
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        raise TypeError("review_statuses must be a list of strings")
    cleaned: list[str] = []
    for value in values:
        status = str(value).strip().lower()
        if status not in ALL_REVIEW_STATUSES:
            raise ValueError(f"unknown review status: {value}")
        cleaned.append(status)
    return cleaned or [DEFAULT_REVIEW_STATUS]


def document_review_status(row: dict[str, Any]) -> str:
    """Effective review status of a row (default accepted_research)."""
    if row.get("doc_review"):
        return str(row["doc_review"])
    return DEFAULT_REVIEW_STATUS


def filter_by_review(
    rows: list[dict[str, Any]], allowed: list[str] | None = None
) -> list[dict[str, Any]]:
    """Keep only rows whose review status is in *allowed* (default: accepted)."""
    wanted = set(normalise_review_statuses(allowed))
    return [row for row in rows if document_review_status(row) in wanted]


async def set_review_status(db: Any, *, doi: str, status: str) -> None:
    """Set a document's review status. Never creates a row."""
    if status not in ALL_REVIEW_STATUSES:
        raise ValueError(f"unknown review status: {status}")
    await db.execute(
        "UPDATE knowledge_graph_nodes "
        "SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb, updated_at = now() "
        "WHERE content_type = 'fulltext_document' AND metadata->>'doi' = $2",
        json.dumps({REVIEW_KEY: status}),
        doi,
    )


async def review_counts(db: Any) -> dict[str, int]:
    """Per-status document counts, so the curation backlog is visible."""
    rows = await db.fetch(
        "SELECT COALESCE(metadata->>'review_status', $1) AS status, count(*) AS n "
        "FROM knowledge_graph_nodes WHERE content_type = 'fulltext_document' "
        "GROUP BY 1",
        DEFAULT_REVIEW_STATUS,
    )
    return {str(r["status"]): int(r["n"]) for r in rows}
