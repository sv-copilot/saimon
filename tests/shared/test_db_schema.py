"""Tests that validate the database schema is properly initialized.

These tests prevent the silent failures that happen when pgvector
is missing — they assert every expected table, index, and seed row
exists after schema.sql is applied.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Constants — must match schema.sql
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "content_type_registry",
    "knowledge_graph_nodes",
    "knowledge_graph_edges",
    "seed_requests",
    "voice_profiles",
    "audit_log",
    "shadow_sources_cache",
}

EXPECTED_INDEXES = {
    "idx_kg_nodes_content_type",
    "idx_kg_nodes_created_at",
    "idx_kg_edges_source",
    "idx_kg_edges_target",
    "idx_seed_requests_status",
    "idx_audit_trace_id",
    "idx_audit_service",
    "idx_shadow_cache_doi",
    "idx_shadow_cache_last_accessed",
}

EXPECTED_CONTENT_TYPES = {
    "blog_post",
    "summary",
    "research_note",
    "social_post",
    "email_draft",
    "press_release",
    "case_study",
    "white_paper",
    "job_posting",
    "meeting_notes",
    "proposal",
    "tutorial",
    "product_review",
    "bibliography",
}

EXPECTED_VOICE_PROFILES = {
    "spencer-default",
    "spencer-formal",
    "spencer-casual",
    "spencer-marketing",
    "spencer-technical",
}

EXPECTED_SEED_REQUESTS = 15  # from schema.sql INSERT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _table_exists(db_pool: Any, table: str) -> bool:
    row = await db_pool.fetchrow(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)",
        table,
    )
    return row["exists"] if row else False


async def _index_exists(db_pool: Any, index: str) -> bool:
    row = await db_pool.fetchrow(
        "SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname = $1)",
        index,
    )
    return row["exists"] if row else False


async def _row_count(db_pool: Any, table: str) -> int:
    row = await db_pool.fetchrow(f"SELECT count(*) as cnt FROM {table}")
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Tests (skip if no DB pool available)
# ---------------------------------------------------------------------------


@pytest.mark.skip_db_if_unavailable
class TestSchemaTablesExist:
    """Every table defined in EXPECTED_TABLES must exist after schema init."""

    @pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
    async def test_table_exists(self, table: str, db_pool):
        assert await _table_exists(db_pool, table), (
            f"Table '{table}' does not exist. "
            f"Check that schema.sql ran successfully — "
            f"pgvector may be missing (install pgvector/pgvector:pg16)."
        )


@pytest.mark.skip_db_if_unavailable
class TestSchemaIndexesExist:
    """Every index defined in EXPECTED_INDEXES must exist after schema init."""

    @pytest.mark.parametrize("index", sorted(EXPECTED_INDEXES))
    async def test_index_exists(self, index: str, db_pool):
        assert await _index_exists(db_pool, index), (
            f"Index '{index}' does not exist. "
            f"Schema init may have failed before index creation."
        )


@pytest.mark.skip_db_if_unavailable
class TestSeedData:
    """Seed data from schema.sql must be present."""

    async def test_content_types_seeded(self, db_pool):
        """All 14 content types are registered."""
        rows = await db_pool.fetch("SELECT name FROM content_type_registry")
        names = {r["name"] for r in rows}
        missing = EXPECTED_CONTENT_TYPES - names
        assert not missing, (
            f"Missing content types: {missing}. "
            f"Seed data may not have loaded."
        )

    async def test_voice_profiles_seeded(self, db_pool):
        """All 5 voice profiles are registered."""
        rows = await db_pool.fetch("SELECT name FROM voice_profiles")
        names = {r["name"] for r in rows}
        missing = EXPECTED_VOICE_PROFILES - names
        assert not missing, f"Missing voice profiles: {missing}"

    async def test_seed_requests_present(self, db_pool):
        """Expected number of seed requests exist."""
        count = await _row_count(db_pool, "seed_requests")
        assert count >= EXPECTED_SEED_REQUESTS, (
            f"Expected >= {EXPECTED_SEED_REQUESTS} seed requests, got {count}"
        )


@pytest.mark.skip_db_if_unavailable
class TestKnowledgeGraphWritable:
    """The knowledge graph must accept inserts and queries."""

    async def test_insert_and_query_node(self, db_pool):
        """A node can be inserted and retrieved."""
        import uuid
        node_id = str(uuid.uuid4())
        await db_pool.execute(
            "INSERT INTO knowledge_graph_nodes (id, title, content_type, body) "
            "VALUES ($1, $2, $3, $4)",
            node_id, "Test Node", "blog_post", "Test body content",
        )
        row = await db_pool.fetchrow(
            "SELECT id, title, content_type FROM knowledge_graph_nodes WHERE id = $1",
            node_id,
        )
        assert row is not None
        assert row["title"] == "Test Node"
        assert row["content_type"] == "blog_post"

        # Cleanup
        await db_pool.execute(
            "DELETE FROM knowledge_graph_nodes WHERE id = $1", node_id,
        )


@pytest.mark.skip_db_if_unavailable
class TestAuditLogWritable:
    """The audit log must accept inserts."""

    async def test_insert_audit_entry(self, db_pool):
        """An audit entry can be written and retrieved."""
        import uuid
        trace_id = str(uuid.uuid4())
        await db_pool.execute(
            "INSERT INTO audit_log (trace_id, service_name, event_type, payload) "
            "VALUES ($1, $2, $3, $4)",
            trace_id, "test-service", "test_event",
            json.dumps({"key": "value"}),
        )
        row = await db_pool.fetchrow(
            "SELECT trace_id, service_name, event_type FROM audit_log WHERE trace_id = $1",
            trace_id,
        )
        assert row is not None
        assert row["service_name"] == "test-service"
        assert row["event_type"] == "test_event"


@pytest.mark.skip_db_if_unavailable
class TestShadowCacheWritable:
    """The shadow sources cache must accept DOI entries."""

    async def test_insert_cache_entry(self, db_pool):
        """A DOI cache entry can be written."""
        await db_pool.execute(
            "INSERT INTO shadow_sources_cache (doi, title, source_index) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT (doi) DO NOTHING",
            "10.1038/test-cache", "Test Paper", "annas_archive",
        )
        row = await db_pool.fetchrow(
            "SELECT doi, title FROM shadow_sources_cache WHERE doi = $1",
            "10.1038/test-cache",
        )
        assert row is not None
        assert row["title"] == "Test Paper"


@pytest.mark.skip_db_if_unavailable
class TestDatabaseConnection:
    """Basic connectivity tests."""

    async def test_can_ping(self, db_pool):
        """SELECT 1 returns successfully."""
        row = await db_pool.fetchrow("SELECT 1 as one")
        assert row["one"] == 1

    async def test_can_query_schema_version(self, db_pool):
        """PostgreSQL version is 16.x."""
        row = await db_pool.fetchrow("SHOW server_version")
        version = row["server_version"]
        assert version.startswith("16"), f"Expected PG16, got {version}"
