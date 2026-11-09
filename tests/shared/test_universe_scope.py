"""Universe scope (#264)."""

from __future__ import annotations

import re
from pathlib import Path

from research_shared.universe import (
    FICTION_ID,
    PERSONAL_ID,
    REALITY_ID,
    may_export,
    may_read,
    scope_ids,
)

SCHEMA = (Path(__file__).resolve().parents[2] / "schema.sql").read_text()


class TestSchemaFile:
    def test_universes_table_exists(self):
        assert "CREATE TABLE IF NOT EXISTS universes" in SCHEMA

    def test_seeded_universes_are_idempotent(self):
        assert "ON CONFLICT (slug) DO NOTHING" in SCHEMA

    def test_backfill_targets_reality(self):
        assert REALITY_ID in SCHEMA

    def test_columns_and_indexes_present(self):
        assert "ADD COLUMN IF NOT EXISTS universe_id" in SCHEMA
        assert "idx_kg_nodes_universe" in SCHEMA

    def test_visibility_is_constrained(self):
        assert re.search(r"visibility\s+TEXT NOT NULL DEFAULT 'public'", SCHEMA)
        assert "CHECK (visibility IN ('public', 'private'))" in SCHEMA


class TestScope:
    def test_no_universe_falls_back_to_reality(self):
        assert scope_ids(None) == {REALITY_ID}

    def test_children_are_included(self):
        scope = scope_ids(FICTION_ID, {FICTION_ID: ["book-1", "book-2"]})
        assert scope == {FICTION_ID, "book-1", "book-2"}

    def test_grandchildren_are_included(self):
        children = {FICTION_ID: ["needle"], "needle": ["book-1"]}
        assert "book-1" in scope_ids(FICTION_ID, children)

    def test_siblings_are_not_included(self):
        children = {FICTION_ID: ["needle", "other-world"]}
        assert scope_ids("needle", children) == {"needle"}

    def test_cycles_terminate(self):
        children = {"a": ["b"], "b": ["a"]}
        assert scope_ids("a", children) == {"a", "b"}


class TestVisibility:
    def test_public_is_readable(self):
        assert may_read(visibility="public", is_owner=False)

    def test_private_needs_the_owner(self):
        assert may_read(visibility="private", is_owner=True)
        assert not may_read(visibility="private", is_owner=False)

    def test_unknown_visibility_is_treated_as_private(self):
        assert not may_read(visibility=None, is_owner=False)

    def test_export_refuses_private(self):
        assert may_export(visibility="public")
        assert not may_export(visibility="private")
        assert not may_export(visibility=None)

    def test_personal_is_the_private_one(self):
        assert PERSONAL_ID != REALITY_ID
