"""Tests for the api-mcp GET /health/s3 endpoint (SAIMON-S3-STORAGE-1, #189)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class _FakeStorage:
    """Stand-in S3Storage whose health_check is deterministic."""

    def __init__(self, result: dict) -> None:
        self._result = result

    def health_check(self) -> dict:
        return self._result


@pytest.fixture
def client():
    from saimon_mcp.api.server import app

    with TestClient(app) as c:
        yield c


def test_health_s3_connected(client):
    with patch(
        "research_shared.s3_storage.S3Storage.from_env",
        return_value=_FakeStorage({"s3": "connected", "bucket": "mybucket"}),
    ):
        resp = client.get("/health/s3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["s3"]["s3"] == "connected"


def test_health_s3_not_configured(client):
    with patch(
        "research_shared.s3_storage.S3Storage.from_env",
        return_value=_FakeStorage({"s3": "not configured", "bucket": None}),
    ):
        resp = client.get("/health/s3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["s3"]["s3"] == "not configured"


def test_health_s3_error(client):
    with patch(
        "research_shared.s3_storage.S3Storage.from_env",
        return_value=_FakeStorage({"s3": "error", "bucket": "b", "error": "boom"}),
    ):
        resp = client.get("/health/s3")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
