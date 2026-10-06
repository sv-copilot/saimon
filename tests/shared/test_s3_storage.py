"""Tests for research_shared.s3_storage — S3 object storage client + helpers.

SAIMON-S3-STORAGE-1 (#189).  All boto3 calls are mocked — no network access.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from research_shared.sources import fulltext_cache_table

FULLTEXT_CACHE_TABLE = fulltext_cache_table()

from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.s3_storage import (
    S3Storage,
    S3StorageError,
    build_fulltext_object_key,
    store_fulltext,
)

FULL_ENV = {
    "SAIMON_S3_ENDPOINT": "nbg1.your-objectstorage.com",
    "SAIMON_S3_ACCESS_KEY": "access-key",
    "SAIMON_S3_SECRET_KEY": "secret-key",
    "SAIMON_S3_BUCKET": "myveryspecificallyuniquestoragename",
}


class FakeS3Client:
    """In-memory stand-in for a boto3 S3 client."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.head_bucket_calls: list[str] = []
        self.head_bucket_error: Exception | None = None

    def head_bucket(self, Bucket: str) -> None:
        self.head_bucket_calls.append(Bucket)
        if self.head_bucket_error is not None:
            raise self.head_bucket_error

    def put_object(self, Bucket: str, Key: str, Body: bytes, **kwargs) -> None:
        self.objects[Key] = bytes(Body)

    def get_object(self, Bucket: str, Key: str):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _BytesReader(self.objects[Key])}

    def generate_presigned_url(self, method: str, Params: dict, ExpiresIn: int) -> str:
        return f"https://example.invalid/{Params['Key']}?expires={ExpiresIn}"


class _BytesReader:
    """Minimal ``Body`` with a ``read()`` method, like boto3 returns."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


# ---------------------------------------------------------------------------
# S3Storage — configuration
# ---------------------------------------------------------------------------


class TestS3StorageConfig:
    def test_from_env_reads_all_vars(self) -> None:
        storage = S3Storage.from_env(FULL_ENV)
        assert storage.configured is True
        assert storage.bucket == "myveryspecificallyuniquestoragename"

    def test_from_env_missing_secret_fails_closed(self) -> None:
        for missing in ("SAIMON_S3_ENDPOINT", "SAIMON_S3_ACCESS_KEY", "SAIMON_S3_SECRET_KEY", "SAIMON_S3_BUCKET"):
            env = dict(FULL_ENV)
            env[missing] = ""
            storage = S3Storage.from_env(env)
            assert storage.configured is False, f"missing {missing} should be unconfigured"

    def test_empty_env_is_unconfigured(self) -> None:
        assert S3Storage.from_env({}).configured is False

    def test_endpoint_url_adds_https_scheme(self) -> None:
        storage = S3Storage.from_env(FULL_ENV)
        assert storage.endpoint_url == "https://nbg1.your-objectstorage.com"

    def test_endpoint_url_preserves_existing_scheme(self) -> None:
        env = dict(FULL_ENV)
        env["SAIMON_S3_ENDPOINT"] = "https://nbg1.your-objectstorage.com"
        assert S3Storage.from_env(env).endpoint_url == "https://nbg1.your-objectstorage.com"


# ---------------------------------------------------------------------------
# S3Storage — operations (mocked boto3 client)
# ---------------------------------------------------------------------------


class TestS3StorageOperations:
    def test_client_fails_closed_when_unconfigured(self) -> None:
        storage = S3Storage.from_env({})
        with pytest.raises(S3StorageError):
            storage.upload_bytes("k", b"data")

    @patch("boto3.client")
    def test_health_check_connected(self, mock_client_factory) -> None:
        fake = FakeS3Client()
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        result = storage.health_check()
        assert result["s3"] == "connected"
        assert result["bucket"] == FULL_ENV["SAIMON_S3_BUCKET"]
        assert fake.head_bucket_calls == [FULL_ENV["SAIMON_S3_BUCKET"]]

    @patch("boto3.client")
    def test_health_check_error_degrades(self, mock_client_factory) -> None:
        fake = FakeS3Client()
        fake.head_bucket_error = RuntimeError("boom")
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        result = storage.health_check()
        assert result["s3"] == "error"

    def test_health_check_unconfigured(self) -> None:
        result = S3Storage.from_env({}).health_check()
        assert result["s3"] == "not configured"

    @patch("boto3.client")
    def test_upload_bytes(self, mock_client_factory) -> None:
        fake = FakeS3Client()
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        key = storage.upload_bytes("fulltext/abc/1.pdf", b"%PDF-1.4", content_type="application/pdf")
        assert key == "fulltext/abc/1.pdf"
        assert fake.objects["fulltext/abc/1.pdf"] == b"%PDF-1.4"

    @patch("boto3.client")
    def test_download_bytes(self, mock_client_factory) -> None:
        fake = FakeS3Client()
        fake.objects["fulltext/abc/1.pdf"] = b"%PDF-1.4"
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        assert storage.download_bytes("fulltext/abc/1.pdf") == b"%PDF-1.4"

    @patch("boto3.client")
    def test_download_bytes_missing_key_returns_none(self, mock_client_factory) -> None:
        fake = FakeS3Client()
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        assert storage.download_bytes("nope") is None

    @patch("boto3.client")
    def test_presigned_url(self, mock_client_factory) -> None:
        fake = FakeS3Client()
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        url = storage.presigned_url("fulltext/abc/1.pdf", expires_in=60)
        assert url is not None
        assert "fulltext/abc/1.pdf" in url

    @patch("boto3.client")
    def test_presigned_url_failure_returns_none(self, mock_client_factory) -> None:
        fake = FakeS3Client()

        def _boom(method, Params, ExpiresIn):
            raise RuntimeError("signing failed")

        fake.generate_presigned_url = _boom
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        assert storage.presigned_url("k") is None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class TestObjectKey:
    def test_build_fulltext_object_key_shape(self) -> None:
        key = build_fulltext_object_key("10.1000/Test", "pdf")
        assert re.fullmatch(r"fulltext/[0-9a-f]{16}/[0-9a-f]{32}\.pdf", key) is not None

    def test_build_fulltext_object_key_is_stable_per_doi(self) -> None:
        a = build_fulltext_object_key("10.1000/xyz", "pdf")
        b = build_fulltext_object_key("10.1000/xyz", "pdf")
        assert a.split("/")[1] == b.split("/")[1]  # DOI hash prefix is stable
        assert a != b  # UUID suffix is unique


# ---------------------------------------------------------------------------
# store_fulltext — upload + cache persistence
# ---------------------------------------------------------------------------


class _RecordingDb:
    """Async DB stand-in that records executed statements."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.args: list[tuple] = []

    async def execute(self, query: str, *args):
        self.statements.append(query)
        self.args.append(args)
        return "OK"


class TestStoreShadowFulltext:
    @patch("boto3.client")
    async def test_uploads_and_persists_key(self, mock_client_factory) -> None:
        fake = FakeS3Client()
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        db = _RecordingDb()

        key = await store_fulltext(
            db,
            storage,
            doi="10.1000/EXAMPLE",
            title="Example Paper",
            data=b"%PDF-1.4 full text",
            file_type="pdf",
            source_index="internet_archive",
        )

        assert key.startswith("fulltext/")
        assert key.endswith(".pdf")
        assert any(key in stored for stored in fake.objects)
        assert len(db.statements) == 1
        assert f"{FULLTEXT_CACHE_TABLE}" in db.statements[0]
        assert "full_text_path" in db.statements[0]
        # canonical DOI is lowercased
        assert db.args[0][0] == "10.1000/example"

    async def test_unconfigured_storage_raises(self) -> None:
        with pytest.raises(S3StorageError):
            await store_fulltext(
                None, S3Storage.from_env({}), doi="10.1000/x", data=b"data"
            )


# ---------------------------------------------------------------------------
# adapter storage — InternetArchiveAdapter.store_fulltext
# ---------------------------------------------------------------------------


class TestAdapterStorage:
    @patch("boto3.client")
    async def test_internet_archive_adapter_stores_full_text(self, mock_client_factory) -> None:
        fake = FakeS3Client()
        mock_client_factory.return_value = fake
        storage = S3Storage.from_env(FULL_ENV)
        db = _RecordingDb()
        adapter = InternetArchiveAdapter()

        key = await adapter.store_fulltext(
            storage,
            db,
            doi="10.1000/IA",
            title="IA Text",
            data=b"djvu text",
            file_type="djvu",
        )

        assert key is not None
        assert key.endswith(".djvu")
        assert len(db.statements) == 1
        assert db.args[0][0] == "10.1000/ia"

    async def test_adapter_store_fulltext_returns_none_when_unconfigured(self) -> None:
        adapter = InternetArchiveAdapter()
        result = await adapter.store_fulltext(
            S3Storage.from_env({}), None, doi="10.1000/IA", title="T", data=b"x"
        )
        assert result is None
