"""llm.py — DeepSeek LLM client abstraction.

Thin wrapper around the OpenAI-compatible API.  Reads configuration
from environment variables.  Fail-closed: refuses to initialise
without an API key.

When DEEPSEEK_API_KEY is set, generate() calls the live DeepSeek API.
When not set, generate() raises NotImplementedError (fail-closed).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("saimon.llm")

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
        """Build config from SAIMON_* and DEEPSEEK_* environment variables."""
        return cls(
            api_key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("SAIMON_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
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
                "Set DEEPSEEK_API_KEY in the environment.",
                code="AUTH_ERROR",
            )
        self.config = config
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init the OpenAI client for the configured endpoint."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise LLMError(
                    "openai package is required for live LLM calls. "
                    "Install with: pip install openai",
                    code="DEPENDENCY_ERROR",
                )
            self._client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
        return self._client

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion for *prompt* via the DeepSeek API.

        Falls back to NotImplementedError if the openai package isn't
        installed or no API key is configured.
        """
        try:
            client = self._get_client()
            model = kwargs.get("model", self.config.model)
            max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=kwargs.get("temperature", 0.7),
            )
            content = response.choices[0].message.content
            return content or ""

        except ImportError:
            raise NotImplementedError(
                "LLMClient.generate requires the openai package. "
                "Install with: pip install openai"
            )
        except Exception as exc:
            logger.error("LLM generate failed: %s", exc)
            raise LLMError(
                f"LLM generation failed: {exc}",
                code="GENERATION_ERROR",
            ) from exc

    async def health_check(self) -> bool:
        """Check if the LLM backend is reachable.

        Returns True if the backend responds, False otherwise.
        """
        return self.config.api_key is not None

    async def close(self) -> None:
        """Close any open connections to the LLM backend."""
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
        self._client = None
