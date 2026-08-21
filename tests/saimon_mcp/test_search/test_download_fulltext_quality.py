"""Tests for the download_fulltext quality gate (SAIMON-OCR-QUALITY-GATE-1, #196).

Exercises ``_download_fulltext_flow`` directly with fakes: corrupted extracted
text must be rejected before any S3/cache/KG write, while clean text ingests.
"""

from __future__ import annotations

import pytest

from research_shared.adapters.base import FulltextFetchResult
from saimon_mcp.search.server import _download_fulltext_flow


class FakeStorage:
    configured = True

    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}

    def upload_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        self.uploaded[key] = data
        return key


class FakeAdapter:
    name = "scihub"

    def __init__(self, data: bytes) -> None:
        self.calls = 0
        self.result = FulltextFetchResult(
            source_index="scihub",
            doi="10.1000/quality",
            data=data,
            file_type="txt",
        )

    async def fetch_fulltext(self, result):
        self.calls += 1
        return self.result


class FakeDB:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, query: str, *args):
        self.executed.append((query, args))
        return "OK"

    async def fetchrow(self, query: str, *args):
        return None

    async def fetchval(self, query: str, *args):
        return None


def _embed(text: str):
    return [0.1] * 768


async def _run(data: bytes, **kwargs) -> dict:
    db = kwargs.pop("db", FakeDB())
    storage = kwargs.pop("storage", FakeStorage())
    adapter = kwargs.pop("adapter", FakeAdapter(data))

    def get_adapter(name: str):
        return adapter if name == adapter.name else None

    defaults = {
        "doi": "10.1000/quality",
        "source": {"source_index": "scihub", "title": "Quality Paper", "doi": "10.1000/quality"},
        "fetch_only": False,
        "embed_fn": _embed,
    }
    defaults.update(kwargs)
    return await _download_fulltext_flow(db, storage, get_adapter, **defaults)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("FULLTEXT_MIN_QUALITY", raising=False)
    yield


CLEAN = ("The quick brown fox jumps over the lazy dog. ") * 40
GARBLED = ("\ufffd\u2588\u2593\x00\x01") * 200


class TestQualityGate:
    async def test_garbled_text_rejected_before_any_write(self) -> None:
        db = FakeDB()
        storage = FakeStorage()
        adapter = FakeAdapter(GARBLED.encode("utf-8", errors="ignore"))
        result = await _run(GARBLED.encode("utf-8", errors="ignore"), db=db, storage=storage, adapter=adapter)

        assert result["ok"] is False
        assert result.get("quality_rejected") is True
        assert result.get("quality_score") < 0.5
        # no S3 upload, no cache row, no KG persistence
        assert storage.uploaded == {}
        assert not any("INSERT INTO shadow_sources_cache" in q for q, _ in db.executed)
        assert not any("knowledge_graph_nodes" in q for q, _ in db.executed)

    async def test_clean_text_ingests(self) -> None:
        db = FakeDB()
        storage = FakeStorage()
        result = await _run(CLEAN.encode("utf-8"), db=db, storage=storage)

        assert result["ok"] is True
        assert result.get("quality_rejected") is None
        assert result["cache_hit"] is False
        assert result["chunk_count"] >= 1
        assert storage.uploaded
        assert any("knowledge_graph_nodes" in q for q, _ in db.executed)
