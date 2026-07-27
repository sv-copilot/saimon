"""llm.py — DeepSeek LLM client abstraction.

Thin wrapper around the OpenAI-compatible API.  Reads configuration
from environment variables.  Fail-closed: refuses to initialise
without an API key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# LLMError
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Raised when an LLM operation fails."""

    def __init__(self, message: str, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# LLMConfig
# ---------------------------------------------------------------------------

@dataclass
class LLMConfig:
    """Configuration for the LLM client.

    All values can be set via environment variables, following the
    SAIMON_ prefix convention.
    """

    api_key: str | None = None
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    timeout: int = 60
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Build config from SAIMON_* environment variables."""
        return cls(
            api_key=os.getenv("SAIMON_API_KEY"),
            base_url=os.getenv("SAIMON_LLM_BASE_URL", "https://api.deepseek.com/v1"),
            model=os.getenv("SAIMON_LLM_MODEL", "deepseek-chat"),
            timeout=int(os.getenv("SAIMON_LLM_TIMEOUT", "60")),
            max_tokens=int(os.getenv("SAIMON_LLM_MAX_TOKENS", "4096")),
        )

    def __repr__(self) -> str:
        """Safe repr that masks the API key."""
        key_display = "***" if self.api_key else None
        return (
            f"LLMConfig(api_key={key_display}, base_url={self.base_url!r}, "
            f"model={self.model!r}, timeout={self.timeout}, "
            f"max_tokens={self.max_tokens})"
        )


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

class LLMClient:
    """Async client for DeepSeek's OpenAI-compatible chat API.

    Fail-closed: raises LLMError if constructed without an API key.
    """

    def __init__(self, config: LLMConfig) -> None:
        if not config.api_key:
            raise LLMError(
                "LLMClient requires an API key. "
                "Set SAIMON_API_KEY in the environment.",
                code="AUTH_ERROR",
            )
        self.config = config

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion for *prompt*.

        In production this calls the DeepSeek API via the openai package.
        For now it raises NotImplementedError — actual network calls
        require a live endpoint.
        """
        raise NotImplementedError(
            "LLMClient.generate requires a live DeepSeek endpoint. "
            "Set SAIMON_API_KEY and ensure network access."
        )
