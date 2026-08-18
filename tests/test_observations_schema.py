"""Static schema test for the verified-observations layer.

Slice SAIMON-OBSERVATIONS-SCHEMA-1 (#82).

``verify/server.py`` and ``generate/server.py`` persist verification results
to four tables — ``observations``, ``observation_verifications``,
``observation_verification_evidence``, and ``observation_relations`` — that
were historically missing from ``schema.sql``.  Every write against them is
wrapped in best-effort ``try/except``, so persistence silently failed.  This
static test guards the schema definition so the tables and their
compatibility columns cannot disappear without a failing test.

No database is required: these are substring/regex assertions against
``schema.sql``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"

TABLES = (
    "observations",
    "observation_verifications",
    "observation_verification_evidence",
    "observation_relations",
)


def _schema_text() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def _table_block(sql: str, table: str) -> str:
    """Return the column body of a CREATE TABLE IF NOT EXISTS statement."""
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table)}\s*\((.*?)\);",
        sql,
        re.DOTALL,
    )
    assert match is not None, (
        f"CREATE TABLE IF NOT EXISTS {table} not found in schema.sql"
    )
    return match.group(1)


class TestObservationsTablesPresent:
    """schema.sql must define all four observation tables idempotently."""

    @pytest.mark.parametrize("table", TABLES)
    def test_table_defined_idempotently(self, table: str) -> None:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in _schema_text()


class TestObservationsColumns:
    """``observations`` must expose every column the servers write/update."""

    def test_metadata_is_jsonb_with_default(self) -> None:
        block = _table_block(_schema_text(), "observations")
        assert re.search(
            r"\bmetadata\s+JSONB\s+NOT\s+NULL\s+DEFAULT\s+'\{\}'", block
        ), "observations.metadata must be JSONB NOT NULL DEFAULT '{}'"

    def test_update_columns_exist(self) -> None:
        block = _table_block(_schema_text(), "observations")
        for col in (
            "verification_status",
            "source_quality_tier",
            "source_quality_score",
            "primacy_tier",
            "updated_at",
        ):
            assert re.search(rf"\b{re.escape(col)}\b", block), (
                f"observations.{col} is missing — verify/server.py writes it"
            )

    def test_id_defaults_to_gen_random_uuid(self) -> None:
        block = _table_block(_schema_text(), "observations")
        assert re.search(r"\bid\s+UUID\s+PRIMARY\s+KEY\s+DEFAULT\s+gen_random_uuid\(\)", block)


class TestVerificationCompatibility:
    """Both INSERT forms used by verify/ and generate/ must be tolerated."""

    def test_verification_id_is_nullable(self) -> None:
        """generate/server.py omits verification_id; verify/server.py includes it."""
        block = _table_block(_schema_text(), "observation_verifications")
        assert re.search(r"\bverification_id\s+UUID\s*,", block), (
            "observation_verifications.verification_id must be nullable "
            "(generate path omits it from its 6-column INSERT)"
        )
        assert not re.search(
            r"\bverification_id\s+UUID\s+NOT\s+NULL", block
        ), "observation_verifications.verification_id must NOT be NOT NULL"

    def test_evidence_metadata_has_default(self) -> None:
        """generate/server.py omits metadata; verify/server.py includes it."""
        block = _table_block(_schema_text(), "observation_verification_evidence")
        assert re.search(
            r"\bmetadata\s+JSONB\s+NOT\s+NULL\s+DEFAULT\s+'\{\}'", block
        ), "observation_verification_evidence.metadata must default to '{}'"


class TestObservationRelations:
    """observation_relations must support the ON CONFLICT upsert the code uses."""

    def test_unique_constraint_on_edge(self) -> None:
        block = _table_block(_schema_text(), "observation_relations")
        assert re.search(
            r"UNIQUE\s*\(\s*source_id\s*,\s*target_id\s*,\s*relation_type\s*\)", block
        ), "observation_relations needs UNIQUE(source_id, target_id, relation_type)"
