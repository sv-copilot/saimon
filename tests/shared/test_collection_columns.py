"""Schema contract for the unified-ingest columns (#244).

These are static assertions on schema.sql so a later edit cannot silently drop
the columns the rest of the unified-ingest chain (#245-#247) depends on.  The
live idempotency proof (apply twice, backfill an existing row) runs against a
scratch database, not here.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA = (Path(__file__).resolve().parents[2] / "schema.sql").read_text()


def test_knowledge_graph_nodes_declares_collection_and_unit_id() -> None:
    block = SCHEMA.split("CREATE TABLE IF NOT EXISTS knowledge_graph_nodes", 1)[1]
    block = block.split(");", 1)[0]
    assert "collection" in block
    assert "unit_id" in block
    assert "DEFAULT 'research'" in block


def test_observations_declares_collection_and_unit_id() -> None:
    block = SCHEMA.split("CREATE TABLE IF NOT EXISTS observations", 1)[1]
    block = block.split(");", 1)[0]
    assert "collection" in block
    assert "unit_id" in block
    assert "DEFAULT 'research'" in block


def test_idempotent_migration_covers_both_tables() -> None:
    assert SCHEMA.count("ADD COLUMN IF NOT EXISTS collection") == 2
    assert SCHEMA.count("ADD COLUMN IF NOT EXISTS unit_id") == 2


def test_collection_is_indexed_on_both_tables() -> None:
    assert "idx_kg_nodes_collection" in SCHEMA
    assert "idx_observations_collection" in SCHEMA
