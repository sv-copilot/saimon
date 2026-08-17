"""Tests for the legal citation graph schema (slice #69).

The legal plugin represents citations as directed ``knowledge_graph_edges``
with a namespaced ``relation_type`` of ``legal.cites`` and case nodes as
``knowledge_graph_nodes`` with ``content_type = 'legal:case'``.  An optional
``legal_cases`` table is materialised via an idempotent, once-only migration.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from plugins.legal import PLUGIN, LegalPlugin, schema_migrations
from plugins.legal.citations import (
    CITES_RELATION_TYPE,
    LEGAL_CASE_CONTENT_TYPE,
    build_case_node,
    build_citation_edge,
    is_citation_edge,
)
from plugins.legal.migrations import apply_schema_migrations, list_migrations
from research_shared.domain_plugin import DomainPlugin

# ---------------------------------------------------------------------------
# fake DB
# ---------------------------------------------------------------------------


class FakeDB:
    """An async DatabasePool-shaped fake that records executed statements."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self._applied: set[str] = set()

    async def execute(self, sql: str, *args: Any) -> None:
        self.executed.append(sql)
        if "insert into schema_migrations" in sql.lower():
            self._applied.add(args[0])

    async def fetchval(self, sql: str, *args: Any) -> Any:
        return args[0] if args[0] in self._applied else None


# ---------------------------------------------------------------------------
# citation edge convention
# ---------------------------------------------------------------------------


class TestCitationEdgeConvention:
    def test_relation_type_is_namespaced(self):
        assert CITES_RELATION_TYPE == "legal.cites"

    def test_build_citation_edge_sets_relation_type(self):
        edge = build_citation_edge("a", "b")
        assert edge["relation_type"] == "legal.cites"

    def test_build_citation_edge_carries_weight_and_position_in_metadata(self):
        edge = build_citation_edge("a", "b", weight=0.8, position=3)
        assert edge["weight"] == 0.8
        assert edge["metadata"]["position"] == 3

    def test_build_citation_edge_merges_extra_metadata(self):
        edge = build_citation_edge("a", "b", extra={"treatment": "positive"})
        assert edge["metadata"]["treatment"] == "positive"

    def test_is_citation_edge(self):
        assert is_citation_edge({"relation_type": "legal.cites"})
        assert not is_citation_edge({"relation_type": "supports"})


# ---------------------------------------------------------------------------
# case node convention
# ---------------------------------------------------------------------------


class TestCaseNodeConvention:
    def test_content_type_is_legal_case(self):
        node = build_case_node("n1")
        assert node["content_type"] == LEGAL_CASE_CONTENT_TYPE

    def test_domain_data_lives_in_metadata_only(self):
        node = build_case_node("n1", court="SCOTUS", jurisdiction="federal")
        assert node["metadata"]["court"] == "SCOTUS"
        assert node["metadata"]["jurisdiction"] == "federal"
        assert "court" not in node

    def test_no_domain_fields_leak_to_top_level(self):
        node = build_case_node("n1", decided_date="2020-01-01")
        assert set(node.keys()) == {"id", "content_type", "metadata"}


# ---------------------------------------------------------------------------
# migration
# ---------------------------------------------------------------------------


class TestMigration:
    def test_migration_file_exists(self):
        migrations = schema_migrations()
        assert migrations
        assert Path(migrations[0]).exists()

    def test_migration_is_idempotent_sql(self):
        sql = Path(schema_migrations()[0]).read_text()
        assert "CREATE TABLE IF NOT EXISTS legal_cases" in sql
        assert "CREATE INDEX IF NOT EXISTS" in sql

    def test_migration_defines_required_columns(self):
        sql = Path(schema_migrations()[0]).read_text()
        for col in (
            "id",
            "citation_string",
            "court",
            "jurisdiction",
            "decided_date",
            "metadata",
        ):
            assert col in sql

    def test_apply_is_idempotent(self):
        db = FakeDB()
        applied = asyncio.run(apply_schema_migrations(db, schema_migrations()))
        assert applied == ["001_legal_cases.sql"]
        assert any("legal_cases" in s for s in db.executed)

        # Second run applies nothing new (bookkeeping table re-asserted, but
        # the legal_cases migration DDL is not re-executed).
        db.executed.clear()
        applied_again = asyncio.run(apply_schema_migrations(db, schema_migrations()))
        assert applied_again == []
        assert not any("legal_cases" in s for s in db.executed)


# ---------------------------------------------------------------------------
# plugin skeleton
# ---------------------------------------------------------------------------


class TestPluginSkeleton:
    def test_plugin_domain(self):
        assert LegalPlugin().domain == "legal"

    def test_plugin_schema_migrations(self):
        assert LegalPlugin().schema_migrations() == schema_migrations()

    def test_module_exposes_plugin(self):
        assert isinstance(PLUGIN, DomainPlugin)

    def test_tools_registered_by_legal_tools_slices(self):
        # Tools arrive incrementally: 1-3 in SAIMON-LEGAL-TOOLS-CORE-1 (#73),
        # 4-6 in SAIMON-LEGAL-TOOLS-AUTH-1 (#74).
        plugin = LegalPlugin()
        names = [tool.name for tool in plugin.tools()]
        assert "legal.parse_citation" in names
        assert "legal.reconcile_citators" in names
        assert "legal.detect_implicit_overruling" in names

    def test_list_migrations_returns_001(self):
        assert any("001_legal_cases.sql" in p for p in list_migrations())
