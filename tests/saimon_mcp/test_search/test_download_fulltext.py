"""Tests for the download_fulltext tool flow (SAIMON-FULLTEXT-RAG-1, #97).

Exercises ``_download_fulltext_flow`` directly with fakes — consent gate,
dedup, S3 upload, extraction, and KG persistence — without network or PG.
"""

from __future__ import annotations

from research_shared.adapters.base import FulltextFetchResult
from saimon_mcp.search.server import _download_fulltext_flow

ALL_FIVE = {"annas_archive", "libgen", "scihub", "internet_archive", "academic_torrents"}


class FakeStorage:
    configured = True

    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}

    def upload_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        self.uploaded[key] = data
        return key


class UnconfiguredStorage:
    configured = False


class FakeAdapter:
    name = "scihub"

    def __init__(self, result: FulltextFetchResult | None = None) -> None:
        self.calls = 0
        self.result = result or FulltextFetchResult(
            source_index="scihub",
            doi="10.1000/example",
            data=b"full text of the paper, " * 200,
            file_type="txt",
        )

    async def fetch_fulltext(self, result):
        self.calls += 1
        return self.result


class FakeDB:
    def __init__(self, cache_row: dict | None = None, meta_row: dict | None = None) -> None:
        self.cache_row = cache_row
        self.meta_row = meta_row
        self.executed: list[tuple[str, tuple]] = []
        self.fetched: list[str] = []

    async def execute(self, query: str, *args):
        self.executed.append((query, args))
        return "OK"

    async def fetchrow(self, query: str, *args):
        self.fetched.append(query)
        if "full_text_path" in query and self.cache_row is not None:
            return dict(self.cache_row)
        if "source_index, title, file_type" in query and self.meta_row is not None:
            return dict(self.meta_row)
        return None


def _embed(text: str):
    return [0.1] * 768


async def _run(source_index: str = "scihub", **kwargs) -> dict:
    db = kwargs.pop("db", FakeDB())
    storage = kwargs.pop("storage", FakeStorage())
    adapter = kwargs.pop("adapter", FakeAdapter())

    def get_adapter(name: str):
        if adapter is None:
            return None
        return adapter if name == adapter.name else None

    defaults = {
        "doi": "10.1000/example",
        "source": {"source_index": source_index, "title": "Example Paper", "doi": "10.1000/example"},
        "fetch_only": False,
        "embed_fn": _embed,
    }
    defaults.update(kwargs)
    return await _download_fulltext_flow(db, storage, get_adapter, **defaults)


# ---------------------------------------------------------------------------
# success + persistence
# ---------------------------------------------------------------------------


class TestFulltextFlow:
    async def test_success_end_to_end(self) -> None:
        db = FakeDB()
        storage = FakeStorage()
        adapter = FakeAdapter()
        result = await _run(db=db, storage=storage, adapter=adapter)

        assert result["ok"] is True
        assert result["cache_hit"] is False
        assert result["s3_key"].startswith("fulltext/")
        assert result["document_node_id"]
        assert result["chunk_count"] >= 1
        assert adapter.calls == 1
        assert len(storage.uploaded) == 1
        # content types registered + doc node + chunk nodes + edges persisted
        assert any("content_type_registry" in q for q, _ in db.executed)
        assert any("knowledge_graph_nodes" in q for q, _ in db.executed)
        assert any("part_of" in q for q, _ in db.executed)

    async def test_fetch_only_skips_ingest(self) -> None:
        db = FakeDB()
        result = await _run(db=db, fetch_only=True)

        assert result["ok"] is True
        assert result["fetch_only"] is True
        assert result["document_node_id"] is None
        assert result["chunk_count"] == 0
        # no content-type or node persistence
        assert not any("content_type_registry" in q for q, _ in db.executed)
        assert not any("knowledge_graph_nodes" in q for q, _ in db.executed)


# ---------------------------------------------------------------------------
# consent + shadow-source gating
# ---------------------------------------------------------------------------


class TestConsent:
    async def test_default_allowlist_allows_all_five(self, monkeypatch) -> None:
        monkeypatch.delenv("FULLTEXT_DOWNLOAD_CONSENT", raising=False)
        for source_index in sorted(ALL_FIVE):
            adapter = FakeAdapter(FulltextFetchResult(
                source_index=source_index,
                doi="10.1000/example",
                data=b"bytes",
                file_type="txt",
            ))
            adapter.name = source_index
            result = await _run(source_index=source_index, adapter=adapter)
            assert result["ok"] is True, source_index

    async def test_blocked_source_returns_blocked(self, monkeypatch) -> None:
        monkeypatch.setenv("FULLTEXT_DOWNLOAD_CONSENT", "libgen")
        result = await _run(source_index="scihub")
        assert result["ok"] is False
        assert result["blocked"] is True
        assert "not in FULLTEXT_DOWNLOAD_CONSENT" in result["error"]

    async def test_shadow_sources_disabled_blocks(self, monkeypatch) -> None:
        monkeypatch.setenv("SHADOW_SOURCES_ENABLED", "false")
        result = await _run(source_index="scihub")
        assert result["ok"] is False
        assert result["blocked"] is True


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------


class TestDedup:
    async def test_cache_hit_skips_download(self) -> None:
        db = FakeDB(cache_row={
            "full_text_path": "fulltext/abc/1.pdf",
            "file_type": "pdf",
            "title": "Cached Paper",
            "source_index": "scihub",
        })
        adapter = FakeAdapter()
        result = await _run(db=db, adapter=adapter)

        assert result["ok"] is True
        assert result["cache_hit"] is True
        assert result["s3_key"] == "fulltext/abc/1.pdf"
        assert adapter.calls == 0


# ---------------------------------------------------------------------------
# failure modes (fail-closed)
# ---------------------------------------------------------------------------


class TestFailureModes:
    async def test_magnet_only_fails_closed(self) -> None:
        adapter = FakeAdapter(FulltextFetchResult(
            source_index="academic_torrents",
            doi="10.1000/example",
            data=None,
            file_type="torrent",
            download_url="magnet:?xt=urn:btih:deadbeef",
        ))
        adapter.name = "academic_torrents"
        result = await _run(source_index="academic_torrents", adapter=adapter)
        assert result["ok"] is False

    async def test_unconfigured_storage_fails_closed(self) -> None:
        result = await _run(storage=UnconfiguredStorage())
        assert result["ok"] is False
        assert "S3 storage failed" in result["error"]

    async def test_no_doi_and_no_source(self) -> None:
        result = await _run(doi=None, source=None)
        assert result["ok"] is False

    async def test_missing_adapter(self) -> None:
        result = await _run(source_index="scihub", adapter=None)
        assert result["ok"] is False
        assert "no adapter registered" in result["error"]
