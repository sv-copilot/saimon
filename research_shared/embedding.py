"""Config-driven embedding backend configuration (saimon-side).

Reads backend + dimension from env so the embedding helper no longer hardcodes
the OpenAI URL/model/key. The local `nomic-embed-text` backend swap lands in
SAIMON-EMBEDDING-LOCAL-1 (#93); this module just removes the hardcoding.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class EmbeddingConfig:
    """Configuration for the embedding backend."""

    backend: str = "openai"
    url: str = "https://api.openai.com/v1/embeddings"
    model: str = "text-embedding-ada-002"
    dimensions: int = 1536
    api_key_env: str = "OPENAI_API_KEY"

    @classmethod
    def from_env(cls) -> EmbeddingConfig:
        """Build config from SAIMON_EMBEDDING_* env vars (defaults = OpenAI)."""
        return cls(
            backend=os.getenv("SAIMON_EMBEDDING_BACKEND", "openai"),
            url=os.getenv(
                "SAIMON_EMBEDDING_URL", "https://api.openai.com/v1/embeddings"
            ),
            model=os.getenv("SAIMON_EMBEDDING_MODEL", "text-embedding-ada-002"),
            dimensions=int(os.getenv("SAIMON_EMBEDDING_DIMENSIONS", "1536")),
            api_key_env=os.getenv("SAIMON_EMBEDDING_API_KEY_ENV", "OPENAI_API_KEY"),
        )
