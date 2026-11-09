"""Structured filters over evidence facts (#275).

`observation_facts` gives a claim a number, a unit, a date span and a confidence.
Without these filters a question like "what changed between 2015 and 2020" is
answered by text similarity alone, which cannot tell a 2019 figure from a 1990
one.

The rule that keeps this honest: **a filter never silently does nothing.** If a
caller asks for a date window and nothing matches, the answer is nothing — not the
unfiltered list. And a result set built without filters is untouched, because
most of the corpus (95%) has no quantitative fact and must stay reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class FactFilter:
    value_min: float | None = None
    value_max: float | None = None
    date_from: str | None = None
    date_to: str | None = None
    topic: str | None = None

    @property
    def active(self) -> bool:
        return any((
            self.value_min is not None, self.value_max is not None,
            self.date_from is not None, self.date_to is not None,
            self.topic is not None,
        ))

    def clause(self, *, alias: str = "knowledge_graph_nodes", first_param: int = 1) -> tuple[str, list]:
        """SQL fragment + params joining observation_facts as ``alias``.facts.

        Returns ``("", [])`` when no filter is set, so an unfiltered query is
        byte-identical to the pre-#275 behaviour.
        """
        if not self.active:
            return "", []

        # Leading AND: the fragment is appended to an existing WHERE clause.
        parts = [
            (
                f" AND EXISTS (SELECT 1 FROM observation_facts facts_kg "
                f"WHERE facts_kg.node_id = {alias}.id"
            )
        ]
        params: list = []
        index = first_param

        if self.value_min is not None:
            parts.append(f" AND facts_kg.value_numeric >= ${index}")
            params.append(self.value_min)
            index += 1
        if self.value_max is not None:
            parts.append(f" AND facts_kg.value_numeric <= ${index}")
            params.append(self.value_max)
            index += 1
        if self.date_from is not None:
            parts.append(f" AND facts_kg.date_end >= ${index}::date")
            params.append(self.date_from)
            index += 1
        if self.date_to is not None:
            parts.append(f" AND facts_kg.date_start <= ${index}::date")
            params.append(self.date_to)
            index += 1
        if self.topic is not None:
            parts.append(f" AND facts_kg.topic = ${index}")
            params.append(self.topic)
            index += 1

        parts.append(")")
        return "".join(parts), params


def parse_filter(parameters: dict) -> FactFilter:
    """Read filter parameters, ignoring blanks. Values are passed through as given."""
    def number(key):
        raw = parameters.get(key)
        if raw in (None, ""):
            return None
        return float(raw)

    def text(key):
        raw = parameters.get(key)
        return None if raw in (None, "") else str(raw)

    def day(key):
        # The driver binds DATE parameters as date objects; passing the ISO string
        # through raised "'str' object has no attribute 'toordinal'" at runtime.
        raw = parameters.get(key)
        if raw in (None, ""):
            return None
        if isinstance(raw, date):
            return raw
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    return FactFilter(
        value_min=number("value_min"),
        value_max=number("value_max"),
        date_from=day("date_from"),
        date_to=day("date_to"),
        topic=text("topic"),
    )
