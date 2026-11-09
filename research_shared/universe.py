"""Universe scope (#264).

`collection` is a provenance label — which ingest produced a row. It must never
gate visibility, because a filter is something a caller can forget and a scope is
something the data cannot escape.

The hierarchy matters: fiction is a parent, each world is a child, books hang off
the world. A series-level continuity check needs the parent; a draft session
wants the book. Neither is a schema change.
"""

from __future__ import annotations

REALITY_ID = "00000000-0000-4000-8000-000000000001"
FICTION_ID = "00000000-0000-4000-8000-000000000002"
PERSONAL_ID = "00000000-0000-4000-8000-000000000003"

VISIBILITIES = ("public", "private")


def scope_ids(universe_id: str | None, children: dict[str, list[str]] | None = None) -> set[str]:
    """The set a default query may see: the universe plus its descendants.

    Returning the caller's own universe alone would hide a book's content from the
    series view; returning everything hides nothing and scopes nothing.
    """
    if not universe_id:
        return {REALITY_ID}
    seen: set[str] = set()
    stack = [universe_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend((children or {}).get(current, []))
    return seen


def may_read(*, visibility: str | None, is_owner: bool) -> bool:
    """A private universe is readable only by its owner. Absence is not public."""
    if (visibility or "private") != "private":
        return True
    return is_owner


def may_export(*, visibility: str | None) -> bool:
    """Export is the boundary where private content must be refused loudly."""
    return (visibility or "private") != "private"
