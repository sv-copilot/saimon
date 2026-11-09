"""Structured facts extracted from observation claims.

The parser turns a sentence into a :class:`Fact` it can defend: every value it
does not find is left ``None`` and explained in ``reasons``. These tests pin the
observable contract — units are normalised, dates are resolved to inclusive
calendar bounds, and geography is never guessed from a named country.
"""

from __future__ import annotations

from datetime import date

import pytest

from research_shared.facts import Fact, parse_fact


class TestScalarValues:
    def test_percentage_with_year(self):
        fact = parse_fact("Unemployment rose to 4.2% in 2023")
        assert fact.value_numeric == 4.2
        assert fact.unit == "percent"
        assert fact.date_start == date(2023, 1, 1)
        assert fact.date_end == date(2023, 12, 31)
        assert fact.date_base_unit == "year"
        assert "value_numeric" not in fact.reasons

    def test_currency_handles_thousands_separators(self):
        fact = parse_fact("Revenue reached $1,250,000 last year")
        assert fact.value_numeric == 1250000.0
        assert fact.unit == "usd"

    def test_plain_count_is_people(self):
        fact = parse_fact("Alaska held 12,300 prisoners")
        assert fact.value_numeric == 12300.0
        assert fact.unit == "people"

    def test_missing_number_is_recorded_not_invented(self):
        fact = parse_fact("Entity resolution links records across systems")
        assert fact.value_numeric is None
        assert fact.value_text is None
        assert "value_numeric" in fact.reasons
        assert fact.reasons["value_numeric"]


class TestDateRanges:
    def test_year_range_spans_both_years(self):
        fact = parse_fact("Between 1990 and 2000 the population grew")
        assert fact.date_start == date(1990, 1, 1)
        assert fact.date_end == date(2000, 12, 31)
        assert fact.date_base_unit == "year"

    def test_single_month_resolves_to_calendar_month(self):
        fact = parse_fact("In March 2024 the rate was 3.1%")
        assert fact.date_start == date(2024, 3, 1)
        assert fact.date_end == date(2024, 3, 31)
        assert fact.date_base_unit == "month"
        assert fact.value_numeric == 3.1
        assert fact.unit == "percent"

    def test_single_quarter_resolves_to_calendar_quarter(self):
        fact = parse_fact("Q2 2018 GDP was 2.4%")
        assert fact.date_start == date(2018, 4, 1)
        assert fact.date_end == date(2018, 6, 30)
        assert fact.date_base_unit == "quarter"
        assert fact.unit == "percent"

    def test_missing_date_is_recorded(self):
        fact = parse_fact("Entity resolution links records across systems")
        assert fact.date_start is None
        assert "date_start" in fact.reasons
        assert fact.reasons["date_start"]

    def test_date_fields_stay_consistent(self):
        claims = [
            "Unemployment rose to 4.2% in 2023",
            "Between 1990 and 2000 the population grew",
            "In March 2024 the rate was 3.1%",
            "Q2 2018 GDP was 2.4%",
            "Alaska held 12,300 prisoners",
        ]
        for claim in claims:
            fact = parse_fact(claim)
            assert fact.date_base_unit in {None, "year", "quarter", "month", "day"}
            if fact.date_start is not None and fact.date_end is not None:
                assert fact.date_end >= fact.date_start


class TestGeography:
    def test_named_country_is_not_geocoded(self):
        fact = parse_fact("Namibia reported a decline in exports")
        assert fact.latitude is None
        assert fact.longitude is None
        assert "latitude" in fact.reasons or "longitude" in fact.reasons


class TestRobustness:
    def test_empty_string_returns_empty_fact(self):
        fact = parse_fact("")
        assert isinstance(fact, Fact)
        assert fact.value_numeric is None
        assert fact.value_text is None
        assert fact.unit is None
        assert fact.date_start is None
        assert fact.date_end is None
        assert fact.date_base_unit is None
        assert fact.latitude is None
        assert fact.longitude is None
        assert fact.confidence == 0.0
        assert isinstance(fact.reasons, dict)

    def test_missing_date_lowers_confidence(self):
        full = parse_fact("Unemployment rose to 4.2% in 2023")
        bare = parse_fact("Entity resolution links records across systems")
        assert 0.0 <= full.confidence <= 1.0
        assert 0.0 <= bare.confidence <= 1.0
        assert bare.confidence < full.confidence

    def test_messy_punctuation_does_not_raise(self):
        messy = ("%$#,;:!?()[]{}<>/\\|@&*_-+=~`\"' " * 20)[:500]
        assert len(messy) == 500
        fact = parse_fact(messy)
        assert isinstance(fact, Fact)
        assert 0.0 <= fact.confidence <= 1.0

class TestMagnitudesAndDimensions:
    """Gaps found by mining research-service: no magnitude multiplier, no unit dimension."""

    def test_billion_multiplier(self):
        fact = parse_fact("Revenue reached $4.2 billion in 2021")
        assert fact.value_numeric == pytest.approx(4.2e9)
        assert fact.unit == "usd"

    def test_million_people(self):
        fact = parse_fact("About 12 million people moved in 2019")
        assert fact.value_numeric == pytest.approx(12e6)
        assert fact.unit == "people"

    def test_plural_distance_unit(self):
        fact = parse_fact("The route is 3 kilometers long")
        assert fact.value_numeric == 3.0
        assert fact.unit == "distance"

    def test_plural_mass_unit(self):
        fact = parse_fact("The shipment weighed 1,200 kilograms")
        assert fact.value_numeric == 1200.0
        assert fact.unit == "mass"

    def test_magnitude_without_currency(self):
        fact = parse_fact("The index grew 3.5 million points")
        assert fact.value_numeric == pytest.approx(3.5e6)

class TestRejectUnquantifiedNumbers:
    """A bare integer is an enumeration or a stray citation year, not a quantity."""

    def test_enumeration_is_not_a_value(self):
        fact = parse_fact("options (1) and (2) are more commonly pursued using rules")
        assert fact.value_numeric is None
        assert "value_numeric" in fact.reasons

    def test_citation_year_is_a_date_not_a_value(self):
        fact = parse_fact("Mohammad Yani and Adila Krisnadhi. 2021. Challenges and approaches")
        assert fact.value_numeric is None
        assert fact.date_start == date(2021, 1, 1)

    def test_bare_integer_without_unit_is_rejected(self):
        fact = parse_fact("Analytics have also been used to rank 151 query results")
        assert fact.value_numeric is None
