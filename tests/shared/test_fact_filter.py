"""Structured filters (#275).

Two properties matter more than the SQL: an inactive filter must leave the query
untouched, and an active filter must never fall back to unfiltered results.
"""

from __future__ import annotations

from datetime import date

from research_shared.fact_filter import FactFilter, parse_filter


class TestInactiveFilter:
    def test_no_parameters_produce_no_clause(self):
        clause, params = FactFilter().clause()
        assert clause == "" and params == []

    def test_blank_parameters_are_treated_as_absent(self):
        fact_filter = parse_filter({"value_min": "", "date_from": None, "topic": ""})
        assert not fact_filter.active
        assert fact_filter.clause() == ("", [])


class TestClause:
    def test_value_range(self):
        clause, params = FactFilter(value_min=1.0, value_max=9.0).clause()
        assert "value_numeric >= $1" in clause
        assert "value_numeric <= $2" in clause
        assert params == [1.0, 9.0]

    def test_date_window_uses_overlap(self):
        clause, params = FactFilter(date_from=date(2015, 1, 1), date_to=date(2020, 12, 31)).clause()
        # A fact overlaps the window when its end is after the start and its
        # start is before the end — not when either bound is contained.
        assert "date_end >= $1::date" in clause
        assert "date_start <= $2::date" in clause
        assert params == [date(2015, 1, 1), date(2020, 12, 31)]

    def test_topic(self):
        clause, params = FactFilter(topic="inflation").clause()
        assert "topic = $1" in clause and params == ["inflation"]

    def test_parameter_numbering_continues_from_caller(self):
        clause, params = FactFilter(value_min=5.0).clause(first_param=4)
        assert "$4" in clause and params == [5.0]

    def test_joins_are_scoped_to_the_alias(self):
        clause, _ = FactFilter(value_min=1.0).clause(alias="kgn")
        assert "facts_kg.node_id = kgn.id" in clause


class TestParse:
    def test_numeric_strings_become_floats(self):
        fact_filter = parse_filter({"value_min": "2.5", "value_max": 10})
        assert fact_filter.value_min == 2.5 and fact_filter.value_max == 10.0

    def test_active_only_when_set(self):
        assert parse_filter({}).active is False
        assert parse_filter({"topic": "rates"}).active is True

class TestClauseShape:
    """The fragment is appended to a WHERE clause, so it must carry its own AND."""

    def test_clause_starts_with_and(self):
        clause, _ = FactFilter(value_min=1.0).clause()
        assert clause.lstrip().startswith("AND EXISTS")

    def test_default_alias_matches_the_unaliased_from(self):
        clause, _ = FactFilter(value_min=1.0).clause()
        assert "knowledge_graph_nodes.id" in clause

class TestDateParsing:
    def test_iso_strings_become_date_objects(self):
        fact_filter = parse_filter({"date_from": "2015-01-01", "date_to": "2020-12-31"})
        assert fact_filter.date_from == date(2015, 1, 1)
        assert fact_filter.date_to == date(2020, 12, 31)

    def test_unparseable_date_is_ignored_not_crashed(self):
        fact_filter = parse_filter({"date_from": "not-a-date"})
        assert fact_filter.date_from is None
        assert not fact_filter.active
