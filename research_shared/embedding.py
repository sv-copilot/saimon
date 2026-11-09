"""Config-driven local embedding backend (saimon-side).

Provides the local `nomic-embed-text` (768-dim) embedding path via
`fastembed` (ONNX/CPU). Replaces the hardcoded OpenAI ada-002 embedding; no
OpenAI URL/model/key or OPENAI_API_KEY dependency remains. Fail-closed: any
failure (missing package, missing model) returns None.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# fastembed model identifier for nomic-embed-text (768-dim). The bare name
# is not a valid fastembed id; the full repo-qualified id is required.
DEFAULT_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_EMBEDDING_DIMENSIONS = 768
# Bundled-model directory populated at Docker build time (SAIMON-EMBEDDING-
# MODEL-BUNDLE-1). When set and present, fastembed loads from this directory
# via ``specific_model_path`` and never hits HuggingFace at runtime.
DEFAULT_EMBEDDING_MODEL_PATH = "/opt/saimon/models/nomic-embed-text-v1.5"


@dataclass
class EmbeddingConfig:
    """Configuration for the embedding backend."""

    backend: str = "local"
    url: str = ""
    model: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    api_key_env: str = ""
    model_path: str = ""

    @classmethod
    def from_env(cls) -> EmbeddingConfig:
        """Build config from SAIMON_EMBEDDING_* env vars (default = local)."""
        return cls(
            backend=os.getenv("SAIMON_EMBEDDING_BACKEND", "local"),
            url=os.getenv("SAIMON_EMBEDDING_URL", ""),
            model=os.getenv("SAIMON_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
            dimensions=int(
                os.getenv("SAIMON_EMBEDDING_DIMENSIONS", str(DEFAULT_EMBEDDING_DIMENSIONS))
            ),
            api_key_env=os.getenv("SAIMON_EMBEDDING_API_KEY_ENV", ""),
            model_path=os.getenv("SAIMON_EMBEDDING_MODEL_PATH", ""),
        )


# ---------------------------------------------------------------------------
# task-prefix text builders (SAIMON-EMBED-TASK-PREFIXES-1)
# ---------------------------------------------------------------------------

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

# nomic-embed-text-v1.5 is trained with these prefixes; embedding both sides
# without them wastes the contrastive objective. Default OFF: the existing corpus
# was embedded without prefixes, so enabling this before a re-embed would put
# queries and documents in different spaces.
_PREFIX_ENV = "SAIMON_EMBED_TASK_PREFIXES"
EMBED_CHAR_CAP = 8000  # matches embed_local's truncation window


def task_prefixes_enabled() -> bool:
    import os

    return os.getenv(_PREFIX_ENV, "0").strip().lower() in {"1", "true", "yes", "on"}


def document_embed_text(body: str, *, max_chars: int = EMBED_CHAR_CAP) -> str:
    """Text to embed for a stored passage. The stored body is never changed.

    Prefix only — no title — so the ingest path and the query-time passage path
    embed identical text for the same chunk.
    """
    text = (body or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    return f"{DOCUMENT_PREFIX}{text}" if task_prefixes_enabled() else text


def query_embed_text(query: str) -> str:
    """Text to embed for a retrieval query."""
    cleaned = (query or "").strip()
    if not task_prefixes_enabled():
        return cleaned
    return f"{QUERY_PREFIX}{cleaned}"


_EMBEDDING_MODEL_CACHE: dict[tuple[str, str], object] = {}


def reset_embedding_cache() -> None:
    """Clear the cached fastembed models (test hook)."""
    _EMBEDDING_MODEL_CACHE.clear()


def resolve_model_path(model_path: str | None) -> str | None:
    """Return a usable bundled-model directory, or None.

    A valid bundle is a directory containing the ONNX model file (either at
    ``onnx/model.onnx`` or ``model.onnx``) alongside the tokenizer/config
    files. Returns the directory path as a string when present, else None.
    """
    if not model_path:
        return None
    path = Path(model_path)
    if (path / "onnx" / "model.onnx").is_file() or (path / "model.onnx").is_file():
        return str(path)
    return None


def _load_model(model_name: str, model_path: str | None) -> Any | None:
    """Return the cached fastembed model, loading it once. None on failure."""
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return None

    cache_key = (model_name, model_path or "")
    model = _EMBEDDING_MODEL_CACHE.get(cache_key)
    if model is not None:
        return model

    kwargs: dict[str, Any] = {}
    if model_path:
        resolved = resolve_model_path(model_path)
        if resolved is None:
            return None
        kwargs["specific_model_path"] = resolved
    try:
        model = TextEmbedding(model_name=model_name, **kwargs)
    except Exception:  # noqa: BLE001 — fail-closed on model load
        return None
    _EMBEDDING_MODEL_CACHE[cache_key] = model
    return model


def embed_local(
    text: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    model_path: str | None = None,
) -> list[float] | None:
    """Embed text with a local fastembed ONNX model (CPU).

    When ``model_path`` is provided, the model is loaded from that bundled
    directory via ``specific_model_path`` (offline). If the directory is
    missing, this returns None rather than falling back to a runtime download.

    Returns None on any failure (fastembed not installed, model missing, or
    unexpected output), preserving the fail-closed contract.
    """
    vectors = embed_many_local(
        [text], model_name, dimensions, model_path
    )
    return vectors[0] if vectors else None


def embed_many_local(
    texts: list[str],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    model_path: str | None = None,
    batch_size: int = 4,
) -> list[list[float] | None]:
    """Embed many texts in bounded batches with one loaded model.

    Two constraints drive the shape of this function:

    * per-chunk calls were minutes for a paper (39 separate embed passes), so
      the model is loaded once and the texts are batched;
    * the service container is capped at 2 GB, and one 39-62 text pass peaks
      near 1.4 GB on its own - enough to OOM the server mid-request. Four at a
      time peaks around 1.2 GB including the model, and 62 chunks still finish
      in under 10 seconds.

    Alignment is preserved: a vector that fails shape validation, or a batch
    that raises, becomes None in place.
    """
    if not texts:
        return []

    model = _load_model(model_name, model_path)
    if model is None:
        return [None for _ in texts]

    out: list[list[float] | None] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        try:
            raw = list(model.embed([text[:8000] for text in batch], batch_size=batch_size))
        except Exception:  # noqa: BLE001 — fail-closed per batch, keep going
            raw = []
        for vector in raw:
            floats = [float(value) for value in vector]
            out.append(floats if len(floats) == dimensions else None)
        if len(raw) < len(batch):
            out.extend([None] * (len(batch) - len(raw)))
    return out[: len(texts)]


def node_embed_text(title: str, body: str = "") -> str:
    """The text a node is embedded on: prefixed body, or title + body."""
    if task_prefixes_enabled():
        return document_embed_text(body)
    return f"{title or ''}\n{body or ''}".strip()


def embed_node_text(
    title: str,
    body: str = "",
    *,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    model_path: str | None = None,
) -> list[float] | None:
    """Embed a KG node's searchable text (title + body) into a vector.

    Returns None for empty input or on embedding failure (fail-closed).

    With task prefixes on, the text matches what ingest embeds (prefix + body);
    with them off, behaviour is byte-identical to the pre-prefix path.
    """
    text = node_embed_text(title, body)
    if not text:
        return None
    if model_path:
        return embed_local(text, model_name, dimensions, model_path)
    return embed_local(text, model_name, dimensions)


async def backfill_null_embeddings(
    pool: Any,
    *,
    embed_fn: Callable[[str, str], list[float] | None] | None = None,
    limit: int = 1000,
) -> dict[str, int]:
    """Embed knowledge-graph nodes whose ``embedding`` column is NULL.

    Idempotent and re-runnable: already-embedded nodes are never selected.
    ``embed_fn`` is injectable for tests; defaults to :func:`embed_node_text`.
    Returns ``{"embedded": n, "failed": n}``.
    """
    if embed_fn is None:
        # The bundled model path has to be passed explicitly: without it fastembed
        # looks in its own cache, finds nothing under local_files_only, and every
        # row fails closed (observed: 8,574 of 8,574 "failed").
        cfg = EmbeddingConfig.from_env()

        def embed(title: str, body: str) -> list[float] | None:
            return embed_node_text(
                title, body, model_name=cfg.model, dimensions=cfg.dimensions,
                model_path=cfg.model_path or None,
            )
    else:
        embed = embed_fn
    rows = await pool.fetch(
        "SELECT id, title, body FROM knowledge_graph_nodes "
        "WHERE embedding IS NULL ORDER BY created_at LIMIT $1",
        limit,
    )
    embedded = 0
    failed = 0
    # Embed in batches: one-at-a-time costs ~0.5 s per row on a 2 GB container,
    # which turns an 8k-row backfill into hours.
    batch_size = 64
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        vectors = None
        if embed_fn is None:
            cfg = EmbeddingConfig.from_env()
            vectors = embed_many_local(
                [node_embed_text(r.get("title") or "", r.get("body") or "") for r in batch],
                cfg.model, cfg.dimensions, cfg.model_path or None,
            )
        for index, row in enumerate(batch):
            vector = vectors[index] if vectors is not None else embed(
                row.get("title") or "", row.get("body") or ""
            )
            if vector is None:
                failed += 1
                continue
            await pool.execute(
                "UPDATE knowledge_graph_nodes "
                "SET embedding = $1, updated_at = now() WHERE id = $2",
                str(vector),
                row["id"],
            )
            embedded += 1
    return {"embedded": embedded, "failed": failed}
