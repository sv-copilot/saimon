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

# Negation cues that flip a passage's stance. Only phrasal or unambiguous forms
# are here: a bare "no" in "no data" or "Inner product ... no index" produced a
# false contradiction on a passage that plainly supported the claim, so the
# classifier now requires the negation to sit immediately before a claim term.
_NEGATION_CUES = (
    "not",
    "never",
    "cannot",
    "can't",
    "doesn't",
    "don't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "without",
    "fails to",
    "failed to",
    "no longer",
    "no support",
    "unsupported",
    "refutes",
    "contradicts",
)

# Distance before a matched token within which a cue counts as negating it.
# English puts the negation before the thing it negates. 25 characters covers
# "does not support HNSW" and "no support for HNSW" without reaching across a
# clause such as "no data loss ... pgvector supports HNSW".
_CUE_WINDOW = 25

# Sentence terminators for the same-sentence requirement.
_SENTENCE_RE = re.compile(r"[^.!?;\n]+")

# Words that may sit between a cue and the claim term without breaking the
# negation ("does not *support* hnsw", "no *support* for hnsw"). Anything else —
# "no longer *fits* ... hnsw" — means the cue is about something else.
_CUE_GAP_TOKENS = frozenset(
    ["a", "an", "any", "are", "be", "been", "by", "directly", "for", "have",
     "is", "it", "necessarily", "of", "support", "supported", "supports", "the",
     "that", "to", "true", "use", "used", "uses", "was", "were", "with"]
)

MIN_SUPPORT_TOKENS = 2
MIN_QUOTE_CHARS = 60
MAX_EVIDENCE_ITEMS = 5

# Anchor terms: what ties a passage to the claim's subject. A proper noun, a
# year, or a long word. Generic terms ("product", "teams", "writing") do not
# qualify, because a passage that shares only those says nothing about the
# claim. This is the gate that stops "Janis wasn't writing about product teams"
# being contradicted by a chapter of Shape Up.
_PROPER_RE = re.compile(r"\b[A-Z][A-Za-z][A-Za-z'-]{1,}\b")
_YEAR_RE = re.compile(r"\b(?:1[89]|20)\d{2}\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_LONG_ANCHOR = 9

# Words that open a sentence as grammar, not as a name.
_SENTENCE_STARTERS = frozenset(
    ["a", "an", "and", "as", "at", "but", "by", "every", "for", "from", "he", "her",
     "here", "his", "how", "i", "if", "in", "is", "it", "its", "many", "more", "most",
     "my", "no", "not", "of", "on", "one", "only", "or", "our", "she", "so", "some",
     "that", "the", "their", "them", "then", "there", "these", "they", "this",
     "those", "to", "two", "under", "was", "we", "were", "what", "when", "where",
     "which", "while", "who", "why", "with", "you", "your"]
)


def anchor_terms(claim: str) -> list[str]:
    """Distinctive subject terms of a claim, lowercased.

    Proper nouns (excluding a sentence's first word, which is capitalised by
    grammar rather than by being a name), years, then long words as a fallback
    when the claim names nothing. Empty means the claim offers no anchor, in
    which case the gate stays open.
    """
    text = (claim or "").strip()
    if not text:
        return []
    anchors: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", sentence)
        for index, word in enumerate(words):
            if not word[:1].isupper() or len(word) < 3:
                continue
            # A sentence opens with a capital by grammar, so only starters that
            # could not be ordinary sentence words ("The", "This", "We") count
            # as names when they sit first.
            if index == 0 and word.lower() in _SENTENCE_STARTERS:
                continue
            if word.lower() not in anchors:
                anchors.append(word.lower())
    for match in _YEAR_RE.finditer(text):
        if match.group(0) not in anchors:
            anchors.append(match.group(0))
    if anchors:
        return anchors
    return [token for token in claim_tokens(text) if len(token) >= _LONG_ANCHOR]


def name_anchors(claim: str) -> list[str]:
    """Anchors that are names rather than years.

    A year alone must not satisfy the subject gate: "Minsky (1974)" contains
    1974 and says nothing about Tversky or Kahneman.
    """
    return [anchor for anchor in anchor_terms(claim) if not _YEAR_RE.fullmatch(anchor)]


def subject_missing(claim: str, passage: str) -> bool:
    """True when the claim names a subject the passage never mentions."""
    anchors = name_anchors(claim) or anchor_terms(claim)
    if not anchors:
        return False
    lowered = (passage or "").lower()
    return not any(anchor in lowered for anchor in anchors)

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


_REFERENCE_HINTS = re.compile(
    r"\bpp?\.\s*\d|\bvol\.\s*\d|\bdoi\b|\bet al\.,?\s*\(?\d{4}|\b\d{1,3}:\d{1,4}[-\u2013]\d",
    re.IGNORECASE)


def looks_like_reference(sentence: str) -> bool:
    """True for a bibliography line rather than a statement.

    A reference entry names an author and a year, so it clears every lexical
    gate while asserting nothing. Two markers together — a year in parentheses
    and a page range, volume, DOI or "et al." — are enough to skip it.
    """
    text = sentence or ""
    if not re.search(r"\(\d{4}[a-z]?\)", text):
        return False
    return bool(_REFERENCE_HINTS.search(text))


def best_sentence(passage: str, claim: str) -> str:
    """The sentence that shares the most with the claim.

    Evidence has to be quotable if it is to be checked by a reader. A 1,400
    character chunk can mention a name once in a reference list and share
    nothing else; the sentence that carries the overlap is what should be cited
    and what should decide the verdict.
    """
    candidates = [s.strip() for s in _SENTENCE_RE.findall(passage or "") if s.strip()]
    assertions = [s for s in candidates if not looks_like_reference(s)]
    if assertions:
        candidates = assertions
    if not candidates:
        return (passage or "").strip()
    scored = [(support_score(claim, sentence), len(sentence), sentence) for sentence in candidates]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][2] if scored else (passage or "").strip()


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

    A passage contradicts when a negation cue sits within ``_CUE_WINDOW``
    characters *before* a matched claim token and in the same sentence. Both
    restrictions matter: an earlier version searched 60 characters either side
    of any token and labelled a pgvector install page "contradicts" because of an
    unrelated word in the surrounding text.

    This is a lexical stand-in for a stance model. It is allowed to miss a
    contradiction (that degrades to a weaker verdict) and it is not allowed to
    invent one, so the rules are deliberately narrow.
    """
    text = (passage or "").lower()
    if subject_missing(claim, passage):
        # Sharing "product" and "teams" is not evidence about Janis. Without
        # this gate the negation rule below turned a generic overlap into
        # "contradicts", which is how an unrelated chapter of Shape Up was
        # recorded as refuting a claim about groupthink.
        return "mentions"
    matched = [t for t in claim_tokens(claim) if t in text]
    if len(matched) < MIN_SUPPORT_TOKENS:
        return "mentions"

    for sentence in _SENTENCE_RE.findall(text):
        hits = [t for t in matched if t in sentence]
        if len(hits) < MIN_SUPPORT_TOKENS:
            continue
        for token in hits:
            start = 0
            while True:
                at = sentence.find(token, start)
                if at == -1:
                    break
                before = sentence[max(0, at - _CUE_WINDOW) : at]
                for cue in _NEGATION_CUES:
                    match = re.search(rf"\b{re.escape(cue)}\b", before)
                    if not match:
                        continue
                    gap = before[match.end() :]
                    gap_tokens = [w for w in re.findall(r"[a-z0-9]+", gap) if w]
                    if all(word in _CUE_GAP_TOKENS for word in gap_tokens):
                        return "contradicts"
                start = at + len(token)
    return "supports"


def claim_is_negated(claim: str) -> bool:
    """True when the claim itself asserts the negative.

    "pgvector does not support HNSW" is contradicted by a passage that says it
    does. Without this, a negated claim was verified as supported by passages
    asserting the opposite — the stance of the passage alone cannot tell you
    which way it lands.
    """
    text = (claim or "").lower()
    return any(re.search(rf"\b{re.escape(cue)}\b", text) for cue in _NEGATION_CUES)


def _invert_stance(polarity: str) -> str:
    if polarity == "supports":
        return "contradicts"
    if polarity == "contradicts":
        return "supports"
    return polarity


def _evidence_sql(scoped: bool) -> str:
    """SQL for one evidence query. `ORDER BY id` is what makes it deterministic."""
    scope_clause = "\n  AND universe_id = ANY($3::uuid[])" if scoped else ""
    return f"""
SELECT id, title, body, content_type,
       COALESCE(metadata->>'doi', '') AS doi,
       COALESCE(metadata->>'path', '') AS path
FROM knowledge_graph_nodes
WHERE content_type IN ('fulltext_document', 'fulltext_chunk', 'claim')
  AND COALESCE(metadata->>'status', 'ready') <> 'failed'
  AND (title ILIKE ANY($1) OR body ILIKE ANY($1) OR COALESCE(metadata->>'path', '') ILIKE ANY($1)){scope_clause}
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

    # Search on the claim's subject, not on its first few words: "product" and
    # "teams" outrank "janis" in claim order and return the wrong corpus.
    terms = anchor_terms(claim)[:4] or tokens[:6]
    patterns = [f"%{token}%" for token in terms]
    if universe_ids is None:
        rows = await db.fetch(EVIDENCE_SQL, patterns, limit)
    else:
        rows = await db.fetch(EVIDENCE_SQL_SCOPED, patterns, limit, sorted(universe_ids))

    negated_claim = claim_is_negated(claim)
    evidence: list[dict[str, Any]] = []
    for row in rows:
        text = f"{row.get('title') or ''} {row.get('body') or ''}"
        sentence = best_sentence(text, claim)
        # Density has to live in the sentence that will be quoted. A chunk that
        # mentions "Kahneman" in a reference list and shares nothing else is not
        # evidence that the claim is true. The title counts for the subject
        # because a document is about what it is named, even when the quoted
        # sentence is a table row that repeats the name once.
        # The path counts too: a governance document about slice states need not
        # repeat the word "Drake", but it lives in drake-governance/.docs.
        titled = f"{row.get('path') or ''} {row.get('title') or ''}. {sentence}"
        if subject_missing(claim, titled):
            continue
        score = support_score(claim, sentence)
        # Without a named subject every matching word is generic, so the bar
        # rises: "acceptance" and "order" appear in a carmaker's annual report.
        required = MIN_SUPPORT_TOKENS if name_anchors(claim) else MIN_SUPPORT_TOKENS + 2
        if score < required:
            continue
        quote = sentence if len(sentence) >= MIN_QUOTE_CHARS else quote_from(
            str(row.get("body") or ""), claim)
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
                "polarity": _invert_stance(classify_stance(claim, titled))
                if negated_claim
                else classify_stance(claim, titled),
            }
        )

    evidence.sort(key=lambda item: (-item["overlap_tokens"], item["evidence_source"]))
    return evidence[:MAX_EVIDENCE_ITEMS]
