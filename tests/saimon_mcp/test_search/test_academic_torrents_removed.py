"""Tests for Academic Torrents removal from the default source list (#201)."""

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
