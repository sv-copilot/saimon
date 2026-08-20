"""Config-driven local embedding backend (saimon-side).

Provides the local `nomic-embed-text` (768-dim) embedding path via
`fastembed` (ONNX/CPU). Replaces the hardcoded OpenAI ada-002 embedding; no
OpenAI URL/model/key or OPENAI_API_KEY dependency remains. Fail-closed: any
failure (missing package, missing model) returns None.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

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
