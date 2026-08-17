"""doctrine_diffusion.py — rule-adoption timeline (legal tool 7/10, #75).

Composes search + generate: track a doctrine's adoption across jurisdictions
over time.  Pure, deterministic logic over recorded case metadata — no network
I/O.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plugins.legal.adapters.base import parse_year


def _jurisdiction_of(case: dict[str, Any]) -> str:
    meta = case.get("metadata", {}) if isinstance(case, dict) else {}
    jurisdiction = meta.get("jurisdiction") or meta.get("state") or ""
    if jurisdiction:
        return str(jurisdiction).strip()
    court = str(meta.get("court", "")).strip()
    return court or "unknown"


def map_doctrine_diffusion(
    cases: list[dict[str, Any]], doctrine: str | None = None
) -> dict[str, Any]:
    """Map a doctrine's adoption across jurisdictions over time.

    Each case contributes its decision year and jurisdiction.  Adoptions are
    ordered by year (then jurisdiction), and the earliest adoption is reported
    as the doctrine's origin.
    """
    name = (doctrine or "doctrine").strip() or "doctrine"

    counts: dict[tuple[int, str], int] = {}
    for case in cases:
        meta = case.get("metadata", {}) if isinstance(case, dict) else {}
        year = parse_year(meta.get("decided_date"))
        if year is None:
            continue
        key = (year, _jurisdiction_of(case))
        counts[key] = counts.get(key, 0) + 1

    adoptions = [
        {"year": year, "jurisdiction": jurisdiction, "case_count": count}
        for (year, jurisdiction), count in sorted(counts.items())
    ]

    jurisdictions: list[str] = []
    seen: set[str] = set()
    for adoption in adoptions:
        jurisdiction = adoption["jurisdiction"]
        if jurisdiction not in seen:
            seen.add(jurisdiction)
            jurisdictions.append(jurisdiction)

    first_adoption = None
    years_to_spread = None
    if adoptions:
        first = adoptions[0]
        first_adoption = {
            "year": first["year"],
            "jurisdiction": first["jurisdiction"],
        }
        years_to_spread = adoptions[-1]["year"] - adoptions[0]["year"]

    if first_adoption is None:
        memo = f"No recorded adoptions of '{name}'."
    else:
        memo = (
            f"'{name}' was first adopted in {first_adoption['jurisdiction']} "
            f"({first_adoption['year']}) and spread to {len(jurisdictions)} "
            f"jurisdiction{'s' if len(jurisdictions) != 1 else ''} over "
            f"{years_to_spread} year{'s' if years_to_spread != 1 else ''}."
        )

    return {
        "doctrine": name,
        "adoptions": adoptions,
        "jurisdictions": jurisdictions,
        "first_adoption": first_adoption,
        "years_to_spread": years_to_spread,
        "memo": memo,
    }


class MapDoctrineDiffusionTool:
    """DomainTool wrapper for :func:`map_doctrine_diffusion`."""

    name = "legal.map_doctrine_diffusion"
    description = (
        "Map a doctrine's adoption across jurisdictions over time, returning "
        "an ordered adoption timeline and a diffusion memo."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "cases": {"type": "array", "items": {"type": "object"}},
            "doctrine": {"type": "string"},
        },
        "required": ["cases"],
    }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        cases = arguments.get("cases")
        if not isinstance(cases, list):
            raise TypeError("Parameter 'cases' must be a list.")
        doctrine = arguments.get("doctrine")
        return map_doctrine_diffusion(cases, doctrine)
