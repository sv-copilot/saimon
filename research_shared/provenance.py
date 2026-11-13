"""Citation records and the verification ledger (#271).

A retrieval result used to come back as a UUID. That is an identifier, not a
citation: it cannot be opened, and it says nothing about the standing of the
source. This module turns a node row into a record a reader can follow, and
records every verdict so a banked answer can be replayed later.

Two rules:

* **A locator is a doi or a URL, never an id.** When neither exists the record
  says so with a reason instead of substituting the node id.
* **A verdict that leaves no trace did not happen.** The ledger is append-only
  and carries the evidence it was based on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

LEDGER_VERSION = "v2"  # v2: stance-aware verdicts (#347 follow-up)


@dataclass
class Citation:
    id: str
    title: str
    content_type: str
    locator: str | None
    locator_reason: str | None = None
    fetched_at: str | None = None
    primacy_tier: str | None = None
    quality_score: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw or {})


def locator_for(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolve a doi or URL; return (locator, reason_when_absent)."""
    meta = _metadata(row)
    doi = (meta.get("doi") or "").strip()
    if doi.startswith("url:"):
        url = doi.split("url:", 1)[1].strip()
        return (url, None) if url else (None, "empty_url")
    if doi:
        return f"doi:{doi}", None
    url = (meta.get("url") or meta.get("source_url") or "").strip()
    if url:
        return url, None
    return None, "no_doi_or_url_in_metadata"


def citation_for(row: dict[str, Any]) -> Citation:
    meta = _metadata(row)
    locator, reason = locator_for(row)
    breakdown_primacy = meta.get("primacy_tier")
    return Citation(
        id=str(row.get("id")),
        title=str(row.get("title") or ""),
        content_type=str(row.get("content_type") or "unknown"),
        locator=locator,
        locator_reason=reason,
        fetched_at=meta.get("fetched_at"),
        primacy_tier=breakdown_primacy,
        quality_score=meta.get("quality_score"),
    )


def claim_hash(claim: str) -> str:
    return hashlib.sha256((claim or "").strip().lower().encode("utf-8")).hexdigest()


def ledger_row(
    *,
    claim: str,
    verdict: str,
    confidence: float,
    citations: list[Citation],
    method: str = "corpus_evidence",
) -> dict[str, Any]:
    """The row written for one verdict."""
    return {
        "claim_hash": claim_hash(claim),
        "claim_text": claim,
        "verdict": verdict,
        "confidence": round(float(confidence), 4),
        "method": method,
        "version": LEDGER_VERSION,
        "evidence_ids": [c.id for c in citations],
        "locators": [c.locator for c in citations if c.locator],
        "evidence_count": len(citations),
    }
