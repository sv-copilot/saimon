"""s3_storage.py — S3-compatible object storage for fetched files.

Backing store for fetched full-text files (books, papers, articles) discovered
through the configured source adapters.  Credentials are read from environment
variables only — never hardcoded — and the client fails closed when any required
variable is missing.

Environment variables (all required for a configured store):

- ``SAIMON_S3_ENDPOINT``  e.g. ``s3.example.com`` (scheme optional)
- ``SAIMON_S3_ACCESS_KEY``
- ``SAIMON_S3_SECRET_KEY``
- ``SAIMON_S3_BUCKET``    e.g. ``my-research-bucket``
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any
from uuid import uuid4

from research_shared.sources import fulltext_cache_table

from research_shared.sources import fulltext_cache_table

logger = logging.getLogger("saimon.s3")

_ENV_ENDPOINT = "SAIMON_S3_ENDPOINT"
_ENV_ACCESS_KEY = "SAIMON_S3_ACCESS_KEY"
_ENV_SECRET_KEY = "SAIMON_S3_SECRET_KEY"
_ENV_BUCKET = "SAIMON_S3_BUCKET"

DEFAULT_REGION = "nbg1"


class S3StorageError(Exception):
    """Raised when S3 storage is used without a valid configuration."""


class S3Storage:
    """Minimal S3-compatible object storage client.

    Wraps a lazily-created ``boto3`` client.  Construction never performs
    network I/O; connectivity is checked explicitly via :meth:`health_check`.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = DEFAULT_REGION,
    ) -> None:
        self.endpoint = (endpoint or "").strip()
        self.access_key = (access_key or "").strip()
        self.secret_key = (secret_key or "").strip()
        self.bucket = (bucket or "").strip()
        self.region = region

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> S3Storage:
        """Build a store from ``SAIMON_S3_*`` environment variables.

        Missing variables yield an *unconfigured* store rather than an
        exception — callers decide whether that is an error via
        :attr:`configured`.
        """
        source = os.environ if env is None else env
        return cls(
            endpoint=source.get(_ENV_ENDPOINT, ""),
            access_key=source.get(_ENV_ACCESS_KEY, ""),
            secret_key=source.get(_ENV_SECRET_KEY, ""),
            bucket=source.get(_ENV_BUCKET, ""),
        )

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        """True when all four required environment variables are non-empty."""
        return bool(
            self.endpoint
            and self.access_key
            and self.secret_key
            and self.bucket
        )

    @property
    def endpoint_url(self) -> str:
        """Endpoint URL with an explicit ``https://`` scheme when absent."""
        endpoint = self.endpoint
        if endpoint.startswith(("http://", "https://")):
            return endpoint
        return f"https://{endpoint}"

    def _client(self) -> Any:
        """Return a lazily-created boto3 S3 client (fail-closed)."""
        if not self.configured:
            raise S3StorageError(
                "S3 storage is not configured — set "
                f"{_ENV_ENDPOINT}, {_ENV_ACCESS_KEY}, {_ENV_SECRET_KEY}, "
                f"and {_ENV_BUCKET}"
            )
        import boto3  # deferred import so the module imports without boto3

        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )

    # ------------------------------------------------------------------
    # operations
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Probe bucket connectivity.  Never raises."""
        if not self.configured:
            return {"s3": "not configured", "bucket": self.bucket or None}
        try:
            self._client().head_bucket(Bucket=self.bucket)
            return {"s3": "connected", "bucket": self.bucket}
        except Exception as exc:  # noqa: BLE001 — health checks degrade, never raise
            logger.warning("S3 health check failed: %s", exc)
            return {"s3": "error", "bucket": self.bucket, "error": str(exc)[:200]}

    def upload_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Upload raw bytes to *key* and return the object key."""
        client = self._client()
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        client.put_object(**kwargs)
        return key

    def download_bytes(self, key: str) -> bytes | None:
        """Download object *key* as bytes, or None on any failure."""
        try:
            client = self._client()
            response = client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"].read()
            return bytes(body)
        except Exception as exc:  # noqa: BLE001 — fail-closed on download errors
            logger.warning("S3 download failed for %r: %s", key, exc)
            return None

    def delete_bytes(self, key: str) -> bool:
        """Delete object *key* from the bucket.  Returns True on success."""
        try:
            client = self._client()
            client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:  # noqa: BLE001 — fail-closed on delete errors
            logger.warning("S3 delete failed for %r: %s", key, exc)
            return False

    def presigned_url(self, key: str, expires_in: int = 3600) -> str | None:
        """Return a presigned GET URL for *key*, or None on failure."""
        try:
            client = self._client()
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed on signing errors
            logger.warning("S3 presigned URL failed for %r: %s", key, exc)
            return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def build_fulltext_object_key(doi: str | None, ext: str) -> str:
    """Return a deterministic, collision-resistant object key for a DOI.

    Format: ``fulltext/{sha1(doi)[:16]}/{uuid4}.{ext}`` — the DOI hash
    provides a stable prefix for bucket listing while the UUID prevents
    collisions between multiple files for the same DOI.
    """
    doi_hash = hashlib.sha1((doi or "").strip().lower().encode()).hexdigest()[:16]
    suffix = (ext or "bin").lstrip(".")
    return f"fulltext/{doi_hash}/{uuid4().hex}.{suffix}"


def _normalize_doi(doi: str) -> str:
    """Canonical DOI form used by ``{fulltext_cache_table()}`` (lowercased, stripped)."""
    return (doi or "").strip().lower()


async def store_fulltext(
    db: Any,
    storage: S3Storage,
    *,
    doi: str,
    data: bytes,
    file_type: str | None = None,
    title: str = "",
    source_index: str | None = None,
) -> str:
    """Upload full-text bytes to S3 and persist the object key in the cache.

    Uploads to ``fulltext/{doi-hash}/{uuid}.{ext}`` and upserts the object
    key into ``{fulltext_cache_table()}.full_text_path`` (plus ``file_type``).
    Returns the S3 object key.
    """
    if not storage.configured:
        raise S3StorageError("S3 storage is not configured — cannot store full text")

    key = build_fulltext_object_key(doi, file_type or "bin")
    storage.upload_bytes(key, data)

    if db is not None:
        await _persist_fulltext_path(db, doi, title, key, file_type, source_index)
    return key


async def _persist_fulltext_path(
    db: Any,
    doi: str,
    title: str,
    key: str,
    file_type: str | None,
    source_index: str | None,
) -> None:
    """Upsert ``full_text_path`` + ``file_type`` for *doi* in the cache table."""
    canonical_doi = _normalize_doi(doi)
    await db.execute(
        f"""
        INSERT INTO {fulltext_cache_table()}
            (doi, title, authors, source_index, file_type, full_text_path, metadata, last_accessed)
        VALUES ($1, $2, '[]'::jsonb, $3, $4, $5, '{{}}'::jsonb, now())
        ON CONFLICT (doi) DO UPDATE SET
            full_text_path = EXCLUDED.full_text_path,
            file_type      = EXCLUDED.file_type,
            ingested_at    = NULL,
            last_accessed  = now()
        """,
        canonical_doi,
        title or "Untitled",
        source_index or "unknown",
        file_type or "bin",
        key,
    )


_ingested_column_ensured = False
_ingested_column_lock: Any | None = None


def reset_ingested_column_guard() -> None:
    """Reset the once-per-process schema guard (test hook)."""
    global _ingested_column_ensured
    _ingested_column_ensured = False


async def ensure_ingested_column(db: Any) -> None:
    """Idempotently add ``{fulltext_cache_table()}.ingested_at`` (once per process).

    Existing databases created before SAIMON-FULLTEXT-DEDUP-FIX-1 do not have
    the column, so this self-heals the schema at the point of first use.
    """
    global _ingested_column_ensured, _ingested_column_lock
    if _ingested_column_ensured:
        return
    if _ingested_column_lock is None:
        import asyncio

        _ingested_column_lock = asyncio.Lock()
    async with _ingested_column_lock:
        if _ingested_column_ensured:
            return
        await db.execute(
            f"ALTER TABLE {fulltext_cache_table()} "
            "ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ"
        )
        _ingested_column_ensured = True


async def mark_fulltext_ingested(db: Any, doi: str) -> None:
    """Mark a DOI's cached full text as fully ingested into the knowledge graph."""
    await db.execute(
        f"UPDATE {fulltext_cache_table()} SET ingested_at = now() WHERE doi = $1",
        _normalize_doi(doi),
    )
