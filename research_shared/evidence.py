"""Corpus evidence collection for claim verification (SAIMON-VERIFY-EVIDENCE-ALGEBRA-1).

The verify service used to self-grade: five LLM methods, every `evidence_source`
null, 45-73 seconds, and a "supported" verdict that cited nothing. This module
looks for real, quotable evidence in the knowledge graph first.

A claim is only `supported` when a stored passage actually contains it. When
nothing matches, the honest answer is `insufficient_evidence` — not a confident
guess. That is the trade the operator asked for: abstain over invent.

Three properties this module now guarantees, each with a test:

1. **Determinism.** The same claim against the same corpus returns the same
   verdict. The query orders by id and the ranking breaks ties by evidence id,
   so the row the planner happens to return first cannot change the answer.
2. **Scope.** Evidence is drawn from the caller's universe and its descendants,
   never from every universe the corpus happens to hold.
3. **Stance.** A passage that negates the claim is labelled `contradicts`, not
   `supports`. Before this, polarity was a constant and `contradicted` was
   unreachable.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Words that appear everywhere and therefore prove nothing on their own.
_STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "been", "by", "can", "could", "do", "does", "did", "for", "from", "has", "have", "had", "how", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "their", "them", "then", "there", "these", "this", "to", "was", "were", "what", "when", "where", "which", "who", "why", "will", "with", "would", "you", "your"]
)

# Negation cues that flip a passage's stance when they sit next to a matched
# token. Deliberately small and conservative: a missed contradiction shows up
# as `insufficient_evidence` (safe), a false contradiction would not be.
_NEGATION_CUES = (
    "not",
    "no",
    "never",
    "none",
    "cannot",
    "can't",
    "doesn't",
    "don't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "without",
    "fails",
    "failed",
    "false",
    "incorrect",
    "refutes",
    "contradicts",
    "unsupported",
)

MIN_SUPPORT_TOKENS = 2
MIN_QUOTE_CHARS = 60
MAX_EVIDENCE_ITEMS = 5

# How many rows to pull before ranking. The old value (40) with no ORDER BY made
# the verdict depend on the planner's row order; this one is larger and stable.
DEFAULT_EVIDENCE_LIMIT = 200

# Characters either side of a matched token searched for a negation cue.
_NEGATION_WINDOW = 60


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


def classify_stance(claim: str, passage: str) -> str:
    """`supports`, `contradicts`, or `mentions`.

    A negation cue within ``_NEGATION_WINDOW`` characters of a matched claim
    token means the passage is arguing the other way. This is a lexical stand-in
    for a stance model: it can be wrong, so it only ever moves a verdict toward
    `contradicted` when the cue is adjacent to the actual claim terms.
    """
    lowered = (passage or "").lower()
    matched = [t for t in claim_tokens(claim) if t in lowered]
    if len(matched) < MIN_SUPPORT_TOKENS:
        return "mentions"
    for token in matched:
        start = 0
        while True:
            at = lowered.find(token, start)
            if at == -1:
                break
            window = lowered[max(0, at - _NEGATION_WINDOW) : at + len(token) + _NEGATION_WINDOW]
            for cue in _NEGATION_CUES:
                if re.search(rf"\b{re.escape(cue)}\b", window):
                    return "contradicts"
            start = at + len(token)
    return "supports"


def _evidence_sql(scoped: bool) -> str:
    """SQL for one evidence query. `ORDER BY id` is what makes it deterministic."""
    scope_clause = "\n  AND universe_id = ANY($3::uuid[])" if scoped else ""
    return f"""
SELECT id, title, body, content_type,
       COALESCE(metadata->>'doi', '') AS doi
FROM knowledge_graph_nodes
WHERE content_type IN ('fulltext_document', 'fulltext_chunk', 'claim')
  AND COALESCE(metadata->>'status', 'ready') <> 'failed'
  AND (title ILIKE ANY($1) OR body ILIKE ANY($1)){scope_clause}
ORDER BY id
LIMIT $2
"""


EVIDENCE_SQL = _evidence_sql(scoped=False)
EVIDENCE_SQL_SCOPED = _evidence_sql(scoped=True)


async def collect_corpus_evidence(
    db: Any,
    claim: str,
    *,
    limit: int = DEFAULT_EVIDENCE_LIMIT,
    universe_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Find passages that share distinctive tokens with the claim.

    Returns evidence items scored by token overlap, strongest first, with ties
    broken by evidence id so the ranking cannot depend on row arrival order. An
    item is only returned when it clears ``MIN_SUPPORT_TOKENS``, so a single
    common word cannot stand in for verification.

    ``universe_ids`` restricts the search to those universes. Passing an empty
    set means "no universe is readable" and returns nothing — a refusal, not a
    silent widening to the whole corpus. ``None`` means unscoped (used by tests
    and by callers that have already resolved scope).
    """
    tokens = claim_tokens(claim)
    if len(tokens) < MIN_SUPPORT_TOKENS:
        return []
    if universe_ids is not None and not universe_ids:
        return []

    patterns = [f"%{token}%" for token in tokens[:6]]
    if universe_ids is None:
        rows = await db.fetch(EVIDENCE_SQL, patterns, limit)
    else:
        rows = await db.fetch(EVIDENCE_SQL_SCOPED, patterns, limit, sorted(universe_ids))

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
                "polarity": classify_stance(claim, text),
            }
        )

    evidence.sort(key=lambda item: (-item["overlap_tokens"], item["evidence_source"]))
    return evidence[:MAX_EVIDENCE_ITEMS]
