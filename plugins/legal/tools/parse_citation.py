"""parse_citation.py — citation normalization (legal tool 1/3, slice #73).

Deterministic regex-first citation parser (architecture §8 Q7): normalize
citations across Bluebook, neutral, and CourtListener URL formats.  Pure logic
— no network I/O.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

# CourtListener opinion URLs: https://www.courtlistener.com/opinion/<id>/<slug>/
_COURTLISTENER_URL_RE = re.compile(r"courtlistener\.com/opinion/(\d+)/")

# Bracketed neutral citations: [2020] UKSC 1 or [2013] EWCA Civ 1
_NEUTRAL_RE = re.compile(r"^\[(\d{4})\]\s+(.+?)\s+(\d+)\s*$")

# Bluebook-style volume/reporter/page, optionally preceded by a case name and
# followed by a decision year: Roe v. Wade, 410 U.S. 113 (1973)
_YEAR_RE = re.compile(r"\((\d{4})\)")
_BLUEBOOK_RE = re.compile(
    r"\b(\d+)\s+([A-Z][A-Za-z0-9.]*(?:\s+[A-Za-z0-9.]+){0,2})\s+(\d+)\b"
)


def _base_result(format_name: str, canonical: str) -> dict[str, Any]:
    return {
        "format": format_name,
        "canonical": canonical,
        "volume": None,
        "reporter": None,
        "page": None,
        "number": None,
        "year": None,
        "court": None,
        "case_id": None,
    }


def parse_citation(citation: str) -> dict[str, Any]:
    """Normalize a citation into a structured dict.

    Formats are detected in priority order: CourtListener URL, bracketed
    neutral citation, then Bluebook-style volume/reporter/page.  Unrecognized
    input returns ``{"format": "unknown", ...}`` with the raw text as
    ``canonical``.
    """
    text = (citation or "").strip()
    if not text:
        raise ValueError("Parameter 'citation' is required.")

    url = _COURTLISTENER_URL_RE.search(text)
    if url:
        case_id = url.group(1)
        result = _base_result("courtlistener_url", f"courtlistener:{case_id}")
        result["case_id"] = case_id
        return result

    neutral = _NEUTRAL_RE.match(text)
    if neutral:
        year = neutral.group(1)
        court = neutral.group(2).strip()
        number = neutral.group(3)
        result = _base_result("neutral", f"[{year}] {court} {number}")
        result["year"] = int(year)
        result["court"] = court
        result["number"] = number
        return result

    bluebook = _BLUEBOOK_RE.search(text)
    if bluebook:
        volume = bluebook.group(1)
        reporter = bluebook.group(2).strip()
        page = bluebook.group(3)
        result = _base_result("bluebook", f"{volume} {reporter} {page}")
        result["volume"] = volume
        result["reporter"] = reporter
        result["page"] = page
        year = _YEAR_RE.search(text)
        if year:
            result["year"] = int(year.group(1))
        return result

    return _base_result("unknown", text)


class ParseCitationTool:
    """DomainTool wrapper for :func:`parse_citation`."""

    name = "legal.parse_citation"
    description = (
        "Normalize a legal citation (Bluebook, neutral, or CourtListener URL) "
        "into a structured dict."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"citation": {"type": "string"}},
        "required": ["citation"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        citation = arguments.get("citation")
        if not citation:
            raise ValueError("Parameter 'citation' is required.")
        return parse_citation(str(citation))
