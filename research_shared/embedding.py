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
from typing import Any

# fastembed model identifier for nomic-embed-text (768-dim). The bare name
# is not a valid fastembed id; the full repo-qualified id is required.
DEFAULT_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_EMBEDDING_DIMENSIONS = 768


@dataclass
class EmbeddingConfig:
    """Configuration for the embedding backend."""

    backend: str = "local"
    url: str = ""
    model: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    api_key_env: str = ""

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
        )


_EMBEDDING_MODEL_CACHE: dict[str, object] = {}


def reset_embedding_cache() -> None:
    """Clear the cached fastembed models (test hook)."""
    _EMBEDDING_MODEL_CACHE.clear()


def embed_local(
    text: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
) -> list[float] | None:
    """Embed text with a local fastembed ONNX model (CPU).

    Returns None on any failure (fastembed not installed, model missing, or
    unexpected output), preserving the fail-closed contract.
    """
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return None

    try:
        model = _EMBEDDING_MODEL_CACHE.get(model_name)
        if model is None:
            model = TextEmbedding(model_name=model_name)
            _EMBEDDING_MODEL_CACHE[model_name] = model
        embeddings = model.embed([text[:8000]])
        vector = next(iter(embeddings), None)
        if vector is None:
            return None
        floats = [float(value) for value in vector]
        if len(floats) != dimensions:
            return None
        return floats
    except Exception:  # noqa: BLE001 — fail-closed on any embedding failure
        return None


def embed_node_text(
    title: str,
    body: str = "",
    *,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
) -> list[float] | None:
    """Embed a KG node's searchable text (title + body) into a vector.

    Returns None for empty input or on embedding failure (fail-closed).
    """
    text = f"{title or ''}\n{body or ''}".strip()
    if not text:
        return None
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
    embed = embed_fn or embed_node_text
    rows = await pool.fetch(
        "SELECT id, title, body FROM knowledge_graph_nodes "
        "WHERE embedding IS NULL ORDER BY created_at LIMIT $1",
        limit,
    )
    embedded = 0
    failed = 0
    for row in rows:
        vector = embed(row.get("title") or "", row.get("body") or "")
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
