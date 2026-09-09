"""Tests for Internet Archive retry-with-backoff (SAIMON-SEARCH-RELIABILITY-1, #201)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx

from research_shared.adapters.internet_archive import InternetArchiveAdapter


def _mock_response(status=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_data or {})
    return resp


def _ok_doc(title: str = "Retried Book"):
    return _mock_response(
        200, {"response": {"docs": [{"identifier": "id1", "title": title}]}}
    )


class TestInternetArchiveRetry:
    def test_retries_once_on_read_timeout(self) -> None:
        adapter = InternetArchiveAdapter()
        client = MagicMock()
        client.get = AsyncMock(
            side_effect=[httpx.ReadTimeout("timeout"), _ok_doc()]
        )
        adapter._http = client

        results = asyncio.run(adapter.search("test"))

        assert len(results) == 1
        assert results[0].title == "Retried Book"
        assert client.get.await_count == 2

    def test_retries_once_on_connect_error(self) -> None:
        adapter = InternetArchiveAdapter()
        client = MagicMock()
        client.get = AsyncMock(
            side_effect=[httpx.ConnectError("connect"), _ok_doc()]
        )
        adapter._http = client

        results = asyncio.run(adapter.search("test"))

        assert len(results) == 1
        assert client.get.await_count == 2

    def test_gives_up_after_retries(self) -> None:
        adapter = InternetArchiveAdapter()
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        adapter._http = client

        results = asyncio.run(adapter.search("test"))

        assert results == []
        assert client.get.await_count == 2

    def test_non_retriable_error_not_retried(self) -> None:
        adapter = InternetArchiveAdapter()
        client = MagicMock()
        client.get = AsyncMock(side_effect=RuntimeError("boom"))
        adapter._http = client

        results = asyncio.run(adapter.search("test"))

        assert results == []
        assert client.get.await_count == 1
