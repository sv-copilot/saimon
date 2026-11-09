"""Structured facts extracted from an evidence node's text (#272).

Saimon stores claims as prose, so a question about a number, a period or a place
can only be answered by hoping a chunk says it, and the heuristics that decide
whether two claims agree have nothing to compare. This module reads the shape out
of the text: one number with its unit, one date span with its granularity.

Deliberate limits:

* **Nothing is guessed.** A field the text does not carry is ``None`` and the
  ``reasons`` map says why. A plausible default is worse than an honest gap —
  the same rule that governs primacy tiers.
* **Geography is not resolved.** There is no gazetteer here, so latitude and
  longitude are always ``None`` with ``no_gazetteer`` recorded. Inventing
  coordinates from a country name would be a fabricated fact.
* **Years are not values.** Numbers inside a date expression are masked before
  value extraction, so "in 2023" never becomes the number 2023.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

PARSER_VERSION = "v1"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

MAGNITUDES = {
    "thousand": 1e3, "k": 1e3,
    "million": 1e6, "mn": 1e6, "m": 1e6,
    "billion": 1e9, "bn": 1e9, "b": 1e9,
    "trillion": 1e12,
}

UNIT_WORDS = {
    "distance": ("kilometer", "kilometers", "kilometre", "kilometres", "km", "mile",
                 "miles", "meter", "meters", "metre", "metres", "mi"),
    "mass": ("kilogram", "kilograms", "kg", "gram", "grams", "pound", "pounds",
             "lb", "lbs", "ton", "tons", "tonne", "tonnes"),
    "temperature": ("celsius", "fahrenheit", "degree", "degrees", "°c", "°f"),
}

PEOPLE_WORDS = (
    "people", "persons", "prisoners", "residents", "employees", "workers",
    "students", "patients", "users", "customers", "inhabitants",
)

_QUARTER_RE = re.compile(r"\bQ([1-4])\s*(?:of\s*)?(\d{4})\b", re.IGNORECASE)
_RANGE_RE = re.compile(
    r"\bbetween\s+(\d{4})\s+and\s+(\d{4})\b|(\d{4})\s*[-–]\s*(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_RE = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{4})\b",
    re.IGNORECASE,
)
_DAY_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2}|21\d{2})\b")
_PERCENT_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(?:%|percent\b)", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"\$\s?(-?\d[\d,]*(?:\.\d+)?)")
_NUMBER_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)")


@dataclass
class Fact:
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None
    date_start: date | None = None
    date_end: date | None = None
    date_base_unit: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    topic: str | None = None
    confidence: float = 0.0
    reasons: dict[str, str] = field(default_factory=dict)


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def _month_span(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month // 12), (month % 12) + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def _quarter_span(year: int, quarter: int) -> tuple[date, date]:
    start_month = 3 * (quarter - 1) + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    last = date(year + (end_month // 12), (end_month % 12) + 1, 1)
    return start, date.fromordinal(last.toordinal() - 1)


def _extract_dates(text: str, fact: Fact) -> list[tuple[int, int]]:
    """Fill date fields; return the (start, end) offsets to mask from the text."""
    spans: list[tuple[int, int]] = []

    match = _RANGE_RE.search(text)
    if match:
        y1, y2 = match.group(1) or match.group(3), match.group(2) or match.group(4)
        a, b = int(y1), int(y2)
        fact.date_start, fact.date_end = date(a, 1, 1), date(b, 12, 31)
        fact.date_base_unit = "year"
        spans.append(match.span())
        return spans

    match = _QUARTER_RE.search(text)
    if match:
        start, end = _quarter_span(int(match.group(2)), int(match.group(1)))
        fact.date_start, fact.date_end, fact.date_base_unit = start, end, "quarter"
        spans.append(match.span())
        return spans

    match = _DAY_RE.search(text)
    if match:
        try:
            day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            day = None
        if day is not None:
            fact.date_start = fact.date_end = day
            fact.date_base_unit = "day"
            spans.append(match.span())
            return spans

    match = _MONTH_RE.search(text)
    if match:
        month = MONTHS[match.group(1).lower().rstrip(".")]
        start, end = _month_span(int(match.group(2)), month)
        fact.date_start, fact.date_end, fact.date_base_unit = start, end, "month"
        spans.append(match.span())
        return spans

    years = list(_YEAR_RE.finditer(text))
    if years:
        year = int(years[0].group(1))
        fact.date_start, fact.date_end = date(year, 1, 1), date(year, 12, 31)
        fact.date_base_unit = "year"
        # Every year is masked, not just the first: a claim that repeats its year
        # otherwise yields that year as its "value".
        spans.extend(match.span() for match in years)

    return spans


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for index in range(start, min(end, len(chars))):
            chars[index] = " "
    return "".join(chars)


def _magnitude_after(text: str, end: int) -> float:
    """A magnitude word immediately after a number multiplies it.

    "$4.2 billion" was unparseable in the old project; the number came back as
    4.2 and the claim's scale was silently lost.
    """
    tail = text[end : end + 24].lower()
    words = re.findall(r"[a-z]+", tail)
    for word in words[:2]:
        if word in MAGNITUDES:
            return MAGNITUDES[word]
        if word not in {"of", "in", "the", "a", "an"}:
            break
    return 1.0


def _unit_word(lowered: str) -> str | None:
    if any(word in lowered for word in PEOPLE_WORDS):
        return "people"
    for dimension, words in UNIT_WORDS.items():
        if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in words):
            return dimension
    if re.search(r"\byears?\b", lowered):
        return "years"
    return None


def _extract_value(text: str, fact: Fact) -> None:
    match = _PERCENT_RE.search(text)
    if match:
        fact.value_numeric = _to_float(match.group(1))
        fact.unit = "percent"
        return

    match = _CURRENCY_RE.search(text)
    if match:
        fact.value_numeric = _to_float(match.group(1)) * _magnitude_after(text, match.end())
        fact.unit = "usd"
        return

    match = _NUMBER_RE.search(text)
    if not match:
        fact.reasons["value_numeric"] = "no_number_in_text"
        return

    unit = _unit_word(text.lower())
    magnitude = _magnitude_after(text, match.end())

    # A bare integer is almost always an enumeration ("options (1) and (2)") or a
    # stray reference, not a comparable quantity. Writing it as a fact would poison
    # the relation and prior stages with numbers that mean nothing.
    if unit is None and magnitude == 1.0:
        fact.reasons["value_numeric"] = "number_without_unit_or_scale"
        fact.reasons["unit"] = "number_without_unit"
        return

    fact.value_numeric = _to_float(match.group(1)) * magnitude
    if unit:
        fact.unit = unit
    else:
        fact.reasons["unit"] = "number_without_unit"


def parse_fact(claim: str) -> Fact:
    """Read the structured shape out of a claim. Never raises."""
    fact = Fact()
    text = (claim or "").strip()
    if not text:
        fact.reasons["text"] = "empty_input"
        return fact

    try:
        spans = _extract_dates(text, fact)
        _extract_value(_mask(text, spans), fact)
    except Exception as exc:  # noqa: BLE001 — fail open by contract
        fact.reasons["parser"] = f"error:{type(exc).__name__}"
        return fact

    if fact.date_start is None:
        fact.reasons["date_start"] = "no_date_expression"
    if fact.date_end is None:
        fact.reasons["date_end"] = "no_date_expression"
    if fact.value_numeric is None and "value_numeric" not in fact.reasons:
        fact.reasons["value_numeric"] = "extraction_failed"
    # No gazetteer: coordinates are never inferred from a place name.
    fact.reasons["latitude"] = "no_gazetteer"
    fact.reasons["longitude"] = "no_gazetteer"

    confidence = 0.2
    if fact.value_numeric is not None:
        confidence += 0.35
    if fact.date_start is not None:
        confidence += 0.35
    if fact.unit:
        confidence += 0.05
    fact.confidence = round(min(confidence, 0.95), 2)
    return fact
