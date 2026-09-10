"""Tests for Academic Torrents removal from the default source list (#201) and
its explicit disablement (#215 / SAIMON-ACADEMIC-TORRENTS-404-1)."""

from __future__ import annotations

from saimon_mcp.search import server as search_server


class TestAcademicTorrentsRemoved:
    def test_default_adapters_exclude_academic_torrents(self) -> None:
        adapters = search_server._get_shadow_adapters()
        names = {a.name for a in adapters}
        assert "academic_torrents" not in names

    def test_default_adapters_keep_book_sources_and_ia(self) -> None:
        adapters = search_server._get_shadow_adapters()
        names = {a.name for a in adapters}
        assert {"annas_archive", "libgen", "scihub", "internet_archive"} <= names

    def test_explicit_academic_torrents_still_available(self) -> None:
        adapters = search_server._get_shadow_adapters(["academic_torrents"])
        names = {a.name for a in adapters}
        assert names == {"academic_torrents"}

    def test_list_source_indexes_marks_academic_torrents_disabled(
        self, client, sample_trace_id, auth_headers
    ) -> None:
        """list_source_indexes reports academic_torrents as disabled, not available."""
        response = client.post(
            "/tools/list_source_indexes",
            json={
                "trace_id": sample_trace_id,
                "content_type": "search",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        indexes = response.json()["data"]["source_indexes"]
        at = [s for s in indexes if s.get("identifier") == "academic_torrents"]
        assert at, "academic_torrents should still be listed (with disabled status)"
        assert at[0]["status"] == "disabled"
        assert "apiv2/search" in at[0].get("disabled_reason", "")
