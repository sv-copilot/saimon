"""Corpus evidence collection for claim verification (SAIMON-VERIFY-EVIDENCE-ALGEBRA-1).

The verify service used to self-grade: five LLM methods, every `evidence_source`
null, 45-73 seconds, and a "supported" verdict that cited nothing. This module
looks for real, quotable evidence in the knowledge graph first.

A claim is only `supported` when a stored passage actually contains it. When
nothing matches, the honest answer is `insufficient_evidence` — not a confident
guess. That is the trade the operator asked for: abstain over invent.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Words that appear everywhere and therefore prove nothing on their own.
_STOPWORDS = frozenset(
    """a an and are as at be been by can could do does did for from has have had how
    in into is it its of on or that the their them then there these this to was were
    what when where which who why will with would you your""".split()
)

MIN_SUPPORT_TOKENS = 2
MIN_QUOTE_CHARS = 60
MAX_EVIDENCE_ITEMS = 5


def claim_tokens(claim: str) -> list[str]:
    """Distinctive tokens of a claim: lowercased, >=4 chars, not stopwords."""
    seen: list[str] = []
    for token in _TOKEN_RE.findall((claim or "").lower()):
        if len(token) < 4 or token in _STOPWORDS or token in seen:
            continue
        seen.append(token)
    return seen


def support_score(claim: str, passage: str) -> int:
    """Count of the claim's distinctive tokens present in a passage."""
    passage_tokens = set(_TOKEN_RE.findall((passage or "").lower()))
    return sum(1 for token in claim_tokens(claim) if token in passage_tokens)


def quote_from(passage: str, claim: str, width: int = 240) -> str:
    """The passage window around the first matching token, for citation."""
    tokens = claim_tokens(claim)
    lowered = (passage or "").lower()
    position = -1
    for token in tokens:
        found = lowered.find(token)
        if found != -1:
            position = found
            break
    if position == -1:
        return (passage or "")[:width]
    start = max(0, position - width // 3)
    return (passage or "")[start : start + width].strip()


EVIDENCE_SQL = """
SELECT id, title, body, content_type,
       COALESCE(metadata->>'doi', '') AS doi
FROM knowledge_graph_nodes
WHERE content_type IN ('fulltext_document', 'fulltext_chunk', 'claim')
  AND COALESCE(metadata->>'status', 'ready') <> 'failed'
  AND (title ILIKE ANY($1) OR body ILIKE ANY($1))
LIMIT $2
"""


async def collect_corpus_evidence(
    db: Any, claim: str, *, limit: int = 40
) -> list[dict[str, Any]]:
    """Find passages that share distinctive tokens with the claim.

    Returns evidence items scored by token overlap, strongest first. An item is
    only returned when it clears ``MIN_SUPPORT_TOKENS``, so a single common word
    cannot stand in for verification (the same failure the retrieval gate fixed).
    """
    tokens = claim_tokens(claim)
    if len(tokens) < MIN_SUPPORT_TOKENS:
        return []

    patterns = [f"%{token}%" for token in tokens[:6]]
    rows = await db.fetch(EVIDENCE_SQL, patterns, limit)

    evidence: list[dict[str, Any]] = []
    for row in rows:
        text = f"{row.get('title') or ''} {row.get('body') or ''}"
        score = support_score(claim, text)
        if score < MIN_SUPPORT_TOKENS:
            continue
        quote = quote_from(str(row.get("body") or ""), claim)
        if len(quote) < MIN_QUOTE_CHARS:
            continue
        evidence.append(
            {
                "evidence_source": str(row.get("id")),
                "title": row.get("title"),
                "content_type": row.get("content_type"),
                "doi": row.get("doi") or None,
                "overlap_tokens": score,
                "quote": quote,
                "polarity": "supports",
            }
        )

    evidence.sort(key=lambda item: item["overlap_tokens"], reverse=True)
    return evidence[:MAX_EVIDENCE_ITEMS]
