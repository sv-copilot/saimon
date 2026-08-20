"""self_extend.py — runtime content type registration.

Provides the self-extension flow: check if a content type is registered,
and if not, research it via LLM and auto-register it in the knowledge
graph's content_type_registry table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# SelfExtendError
# ---------------------------------------------------------------------------

class SelfExtendError(Exception):
    """Raised when self-extension fails."""

    def __init__(self, message: str, code: str = "SELF_EXTEND_ERROR") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# SelfExtendConfig
# ---------------------------------------------------------------------------

@dataclass
class SelfExtendConfig:
    """Configuration for the self-extension flow."""

    llm_model: str = "deepseek-v4-pro"
    research_temperature: float = 0.3
    max_research_tokens: int = 1024
    fallback_description: str = "Auto-registered content type."

    @classmethod
    def from_env(cls) -> SelfExtendConfig:
        """Build config from SAIMON_SE_* environment variables."""
        import os

        return cls(
            llm_model=os.getenv("SAIMON_SE_LLM_MODEL", "deepseek-v4-pro"),
            research_temperature=float(
                os.getenv("SAIMON_SE_RESEARCH_TEMP", "0.3")
            ),
            max_research_tokens=int(
                os.getenv("SAIMON_SE_MAX_TOKENS", "1024")
            ),
            fallback_description=os.getenv(
                "SAIMON_SE_FALLBACK_DESC", "Auto-registered content type."
            ),
        )


# ---------------------------------------------------------------------------
# ContentTypeRegistry
# ---------------------------------------------------------------------------

class ContentTypeRegistry:
    """Database-backed registry for content types.

    Wraps the ``content_type_registry`` PostgreSQL table.  All methods
    are async and delegate to a DatabasePool.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def is_registered(self, name: str) -> bool:
        """Check whether a content type is registered.

        Args:
            name: Content type name (e.g. ``"blog_post"``).

        Returns:
            ``True`` if the type exists in the registry.
        """
        row = await self._db.fetchval(
            "SELECT true FROM content_type_registry WHERE name = $1",
            name,
        )
        return row is not None

    async def get_type(self, name: str) -> dict[str, Any] | None:
        """Get the full definition of a registered content type.

        Args:
            name: Content type name.

        Returns:
            Dict with keys ``name``, ``description``, ``required_params``,
            ``optional_params``, ``voice_profile``, or ``None`` if not found.
        """
        row = await self._db.fetchrow(
            "SELECT name, description, required_params, optional_params, "
            "voice_profile FROM content_type_registry WHERE name = $1",
            name,
        )
        return dict(row) if row else None

    async def register(
        self,
        name: str,
        description: str,
        required_params: list[dict[str, Any]],
        optional_params: list[dict[str, Any]],
        voice_profile: str | None = None,
    ) -> dict[str, Any]:
        """Register a new content type.

        Args:
            name: Unique content type name.
            description: Human-readable description.
            required_params: List of required parameter definitions.
            optional_params: List of optional parameter definitions.
            voice_profile: Optional voice profile name.

        Returns:
            Dict representing the newly registered row.
        """
        import json as _json

        await self._db.execute(
            "INSERT INTO content_type_registry "
            "(name, description, required_params, optional_params, voice_profile) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (name) DO UPDATE SET "
            "description = EXCLUDED.description, "
            "required_params = EXCLUDED.required_params, "
            "optional_params = EXCLUDED.optional_params, "
            "voice_profile = EXCLUDED.voice_profile, "
            "updated_at = now()",
            name,
            description,
            _json.dumps(required_params),
            _json.dumps(optional_params),
            voice_profile,
        )
        return {
            "name": name,
            "description": description,
            "required_params": required_params,
            "optional_params": optional_params,
            "voice_profile": voice_profile,
        }

    async def list_types(self) -> list[dict[str, Any]]:
        """List all registered content types.

        Returns:
            List of dicts, each with keys ``name``, ``description``,
            ``required_params``, ``optional_params``, ``voice_profile``.
        """
        rows = await self._db.fetch(
            "SELECT name, description, required_params, optional_params, "
            "voice_profile FROM content_type_registry ORDER BY name"
        )
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# SelfExtender
# ---------------------------------------------------------------------------

# The research prompt template sent to the LLM when a content type
# is unknown and needs to be researched.
_RESEARCH_PROMPT = """You are a content-type architect for a knowledge-management platform.

Analyze the content type "{name}" and return a JSON object with:

- "description": A 1-2 sentence description of what this content type represents.
- "required_params": A JSON array of required parameter objects, each with:
    "name", "type" (one of str, int, float, bool, list[str]), and "description".
- "optional_params": A JSON array of optional parameter objects (same shape).
- "voice_profile": A suggested voice profile name, or null if none fits.

Return ONLY valid JSON — no markdown, no commentary."""


class SelfExtender:
    """Orchestrates the self-extension flow.

    When asked to ensure a content type exists, checks the registry
    first.  If the type is missing, researches it via LLM and
    auto-registers it.  Degrades gracefully: if the LLM is unavailable
    or returns bad data, registers with fallback defaults.
    """

    def __init__(
        self,
        registry: ContentTypeRegistry,
        llm: Any,
        config: SelfExtendConfig | None = None,
    ) -> None:
        self._registry = registry
        self._llm = llm
        self._config = config or SelfExtendConfig()

    async def ensure_type(self, name: str) -> dict[str, Any]:
        """Ensure a content type is registered.

        If the type already exists, returns its definition immediately.
        If not, researches it via LLM and auto-registers.  Degrades
        gracefully on LLM failure.

        Args:
            name: Content type name (normalised to lowercase/snake_case).

        Returns:
            Dict with ``name``, ``description``, ``required_params``,
            ``optional_params``, ``voice_profile``.

        Raises:
            SelfExtendError: If the name is empty or whitespace-only.
        """
        # --- normalise name ---
        name = name.strip().lower().replace(" ", "_")
        if not name:
            raise SelfExtendError(
                "Content type name must not be empty.",
                code="INVALID_NAME",
            )

        # --- check registry ---
        existing = await self._registry.get_type(name)
        if existing is not None:
            return existing

        # --- research via LLM ---
        researched = await self._research(name)

        # --- register ---
        return await self._registry.register(
            name=name,
            description=researched["description"],
            required_params=researched["required_params"],
            optional_params=researched["optional_params"],
            voice_profile=researched.get("voice_profile"),
        )

    async def list_registered_types(self) -> list[dict[str, Any]]:
        """List all registered content types.

        Returns:
            List of type definition dicts.
        """
        return await self._registry.list_types()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    async def _research(self, name: str) -> dict[str, Any]:
        """Research a content type via LLM.

        Returns a dict with ``description``, ``required_params``,
        ``optional_params``, and ``voice_profile``.  Degrades to
        fallback defaults if the LLM fails.
        """
        try:
            prompt = _RESEARCH_PROMPT.format(name=name)
            raw = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._config.llm_model,
                temperature=self._config.research_temperature,
                max_tokens=self._config.max_research_tokens,
            )
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return self._fallback_result()
        except Exception:  # noqa: BLE001 — graceful degradation on any LLM failure
            return self._fallback_result()

        return {
            "description": parsed.get("description", self._config.fallback_description),
            "required_params": parsed.get("required_params", []),
            "optional_params": parsed.get("optional_params", []),
            "voice_profile": parsed.get("voice_profile"),
        }

    def _fallback_result(self) -> dict[str, Any]:
        """Return a safe fallback when LLM research fails."""
        return {
            "description": self._config.fallback_description,
            "required_params": [],
            "optional_params": [],
            "voice_profile": None,
        }
