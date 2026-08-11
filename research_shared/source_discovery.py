"""source_discovery.py — Tier A deterministic reference extraction.

Port of backend/services/source_discovery_service.py Tier A logic.
Extracts DOIs, URLs, and arXiv IDs from text using regex patterns.
No API calls — pure deterministic extraction.

Tier B configuration — when Tier A finds too few candidates, the search MCP
can fall back to Serper.dev web search. See SOURCE_DISCOVERY_MIN_CANDIDATES.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse, urlunparse

# ── Tier B config ──────────────────────────────────────────────────

SOURCE_DISCOVERY_MIN_CANDIDATES = int(
    os.environ.get("SOURCE_DISCOVERY_MIN_CANDIDATES", "3")
)

# ── Reference section heading ───────────────────────────────────────

_REFERENCE_SECTION_HEADING = re.compile(
    r"(?m)^\s*(references|bibliography|cited\s+references|citations)\s*:?\s*$",
    re.IGNORECASE,
)

# ── Patterns (ported from source_discovery_service.py:44-52) ──────

_DOI_PATTERN = re.compile(r"\b(10\.\d{4,9}/[^\s\],;)>\]]+)", re.IGNORECASE)

_URL_PATTERN = re.compile(r"(https?://[^\s\],;)>\]\"']+)", re.IGNORECASE)

_ARXIV_COLON_PATTERN = re.compile(
    r"\barxiv:\s*([0-9]{4}\.\d{4,5}(?:v\d+)?)\b",
    re.IGNORECASE,
)

# ── Normalization (ported from source_discovery_service.py:72-90) ─

def _normalize_doi(raw: str) -> str:
    """Lowercase and strip trailing punctuation from a DOI."""
    d = _strip_trailing_punct(unquote(raw.strip()))
    return d.lower()


def _normalize_url_key(url: str) -> str:
    """Normalize a URL for dedup: strip trailing slash, lowercase."""
    raw = _strip_trailing_punct(url.strip())
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", "", ""))


def _strip_trailing_punct(s: str) -> str:
    """Strip trailing punctuation that regex might capture."""
    return s.rstrip(".,;)'\"”’")


def _doi_from_doi_org_url(url: str) -> str | None:
    """Extract a DOI from a doi.org/dx.doi.org URL."""
    parsed = urlparse(_strip_trailing_punct(url.strip()))
    host = (parsed.netloc or "").lower()
    if host not in ("doi.org", "www.doi.org", "dx.doi.org"):
        return None
    path = (parsed.path or "").lstrip("/")
    if not path.startswith("10."):
        return None
    return _normalize_doi(path)


def _prefer_reference_section(text: str) -> str:
    """If text contains a References/Bibliography heading, prefer text after it."""
    match = _REFERENCE_SECTION_HEADING.search(text)
    if match:
        return text[match.end():].lstrip()
    return text


# ── Candidate model ──────────────────────────────────────────────

@dataclass
class SourceDiscoveryCandidate:
    """One proposed reference extracted from text (DOI, URL, or arXiv)."""

    kind: str  # "doi", "url", "arxiv"
    label: str  # "10.xxx", "https://...", "2301.12345"
    doi: str | None = None
    url: str | None = None
    arxiv_id: str | None = None
    start_index: int = 0


# ── Candidate builders ────────────────────────────────────────────

def _candidate_doi(doi: str, pos: int) -> SourceDiscoveryCandidate:
    normalized = _normalize_doi(doi)
    return SourceDiscoveryCandidate(
        kind="doi",
        label=normalized,
        doi=normalized,
        url=f"https://doi.org/{normalized}",
        arxiv_id=None,
        start_index=pos,
    )


def _candidate_url(url: str, pos: int) -> SourceDiscoveryCandidate:
    cleaned = _strip_trailing_punct(url.strip())
    key = _normalize_url_key(cleaned)
    return SourceDiscoveryCandidate(
        kind="url",
        label=key,
        doi=None,
        url=cleaned,
        arxiv_id=None,
        start_index=pos,
    )


def _candidate_arxiv(arxiv_id: str, pos: int) -> SourceDiscoveryCandidate:
    aid = arxiv_id.strip()
    url = f"https://arxiv.org/abs/{aid}"
    return SourceDiscoveryCandidate(
        kind="arxiv",
        label=aid,
        doi=None,
        url=url,
        arxiv_id=aid,
        start_index=pos,
    )


# ── Main extraction function ──────────────────────────────────────

def extract_reference_candidates(
    text: str, max_results: int = 10
) -> list[SourceDiscoveryCandidate]:
    """Extract DOIs, URLs, and arXiv IDs from text.

    Deterministic extraction using regex patterns. No API calls.
    Deduplicates by normalized key (doi/url/arxiv_id).
    Sorts by position in text (document order).
    Handles doi.org URLs and arxiv.org/abs/ URLs.

    Args:
        text: The input text to scan for references.
        max_results: Maximum number of candidates to return (default 10).

    Returns:
        List of SourceDiscoveryCandidate objects in document order.
    """
    if not text or not text.strip():
        return []

    # Prefer reference section if present
    window = _prefer_reference_section(text)

    seen: set[str] = set()
    events: list[tuple[int, str, SourceDiscoveryCandidate]] = []

    # ── DOI matches ──
    for m in _DOI_PATTERN.finditer(window):
        raw = m.group(1)
        normalized = _normalize_doi(raw)
        if not normalized or not normalized.startswith("10."):
            continue
        key = f"doi:{normalized}"
        events.append((m.start(), key, _candidate_doi(raw, m.start())))

    # ── arXiv: prefix matches ──
    for m in _ARXIV_COLON_PATTERN.finditer(window):
        aid = m.group(1)
        key = f"arxiv:{aid.lower()}"
        events.append((m.start(), key, _candidate_arxiv(aid, m.start())))

    # ── URL matches ──
    for m in _URL_PATTERN.finditer(window):
        raw = m.group(1)
        cleaned = _strip_trailing_punct(raw.strip())
        if not cleaned:
            continue

        # arxiv.org/abs/... → classify as arxiv, not url
        arxiv_m = re.match(
            r"https?://(?:www\.)?arxiv\.org/abs/([0-9]{4}\.\d{4,5}(?:v\d+)?)",
            cleaned,
            re.IGNORECASE,
        )
        if arxiv_m:
            aid = arxiv_m.group(1)
            key = f"arxiv:{aid.lower()}"
            events.append((m.start(), key, _candidate_arxiv(aid, m.start())))
            continue

        # doi.org/... → classify as doi, not url
        doi_from_url = _doi_from_doi_org_url(cleaned)
        if doi_from_url:
            key = f"doi:{doi_from_url}"
            events.append((m.start(), key, _candidate_doi(doi_from_url, m.start())))
            continue

        key = f"url:{_normalize_url_key(cleaned)}"
        events.append((m.start(), key, _candidate_url(cleaned, m.start())))

    # Sort by position in text (document order), then emit with dedup
    events.sort(key=lambda e: e[0])
    out: list[SourceDiscoveryCandidate] = []
    for _pos, key, cand in events:
        if key in seen:
            continue
        if len(out) >= max_results:
            break
        seen.add(key)
        out.append(cand)

    return out
