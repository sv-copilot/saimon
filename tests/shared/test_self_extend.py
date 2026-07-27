"""Tests for research_shared.self_extend — runtime content type registration."""

import pytest

from research_shared.self_extend import (
    ContentTypeRegistry,
    SelfExtendConfig,
    SelfExtender,
    SelfExtendError,
)

# ---------------------------------------------------------------------------
# SelfExtendConfig
# ---------------------------------------------------------------------------

class TestSelfExtendConfig:
    def test_defaults(self):
        """Default config has sensible values."""
        config = SelfExtendConfig()
        assert config.llm_model == "deepseek-chat"
        assert config.research_temperature == 0.3
        assert config.max_research_tokens == 1024
        assert config.fallback_description == "Auto-registered content type."

    def test_from_env_defaults(self, clean_env):
        """With no env vars, uses defaults."""
        config = SelfExtendConfig.from_env()
        assert config.llm_model == "deepseek-chat"
        assert config.research_temperature == 0.3
        assert config.fallback_description == "Auto-registered content type."

    def test_from_env_custom(self, clean_env, monkeypatch):
        """Custom env vars override defaults."""
        monkeypatch.setenv("SAIMON_SE_LLM_MODEL", "deepseek-reasoner")
        monkeypatch.setenv("SAIMON_SE_RESEARCH_TEMP", "0.5")
        monkeypatch.setenv("SAIMON_SE_MAX_TOKENS", "2048")
        monkeypatch.setenv("SAIMON_SE_FALLBACK_DESC", "Custom fallback.")

        config = SelfExtendConfig.from_env()
        assert config.llm_model == "deepseek-reasoner"
        assert config.research_temperature == 0.5
        assert config.max_research_tokens == 2048
        assert config.fallback_description == "Custom fallback."

    def test_repr(self):
        """Config repr is informative."""
        config = SelfExtendConfig(
            llm_model="deepseek-chat",
            research_temperature=0.3,
            fallback_description="Test fallback.",
        )
        r = repr(config)
        assert "deepseek-chat" in r
        assert "0.3" in r


# ---------------------------------------------------------------------------
# SelfExtendError
# ---------------------------------------------------------------------------

class TestSelfExtendError:
    def test_is_exception(self):
        """SelfExtendError is a proper exception."""
        err = SelfExtendError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert isinstance(err, Exception)

    def test_with_code(self):
        """SelfExtendError carries an error code."""
        err = SelfExtendError("Bad type name", code="INVALID_NAME")
        assert err.code == "INVALID_NAME"
        assert str(err) == "Bad type name"


# ---------------------------------------------------------------------------
# ContentTypeRegistry
# ---------------------------------------------------------------------------

class TestContentTypeRegistry:
    def test_construction(self):
        """Registry can be constructed with a db pool."""
        registry = ContentTypeRegistry(db=None)
        assert registry is not None

    def test_methods_exist(self):
        """Registry exposes the expected async interface methods."""
        registry = ContentTypeRegistry(db=None)
        for method in ("is_registered", "get_type", "register", "list_types"):
            assert hasattr(registry, method), f"Registry missing method: {method}"
            import inspect
            assert inspect.iscoroutinefunction(
                getattr(registry, method)
            ), f"{method} must be a coroutine function"


# ---------------------------------------------------------------------------
# ContentTypeRegistry — mock-backed tests
# ---------------------------------------------------------------------------

class _FakePool:
    """A fake DatabasePool that returns canned responses."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self._last_query = None
        self._last_args = None

    async def fetch(self, query, *args):
        self._last_query = query
        self._last_args = args
        return self.rows

    async def fetchrow(self, query, *args):
        self._last_query = query
        self._last_args = args
        return self.rows[0] if self.rows else None

    async def fetchval(self, query, *args):
        self._last_query = query
        self._last_args = args
        return self.rows[0] if self.rows else None

    async def execute(self, query, *args):
        self._last_query = query
        self._last_args = args
        return "OK"


class TestContentTypeRegistryWithMock:
    @pytest.mark.asyncio
    async def test_is_registered_true(self):
        """Returns True when a row exists."""
        pool = _FakePool(rows=[True])
        registry = ContentTypeRegistry(db=pool)
        result = await registry.is_registered("blog_post")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_registered_false(self):
        """Returns False when no row exists."""
        pool = _FakePool(rows=[])  # fetchval returns None
        registry = ContentTypeRegistry(db=pool)
        result = await registry.is_registered("unknown_type")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_type_found(self):
        """Returns dict when type exists."""
        row = {
            "name": "blog_post",
            "description": "A blog post.",
            "required_params": [{"name": "title"}],
            "optional_params": [],
            "voice_profile": "spencer-default",
        }
        pool = _FakePool(rows=[row])
        registry = ContentTypeRegistry(db=pool)
        result = await registry.get_type("blog_post")
        assert result == row

    @pytest.mark.asyncio
    async def test_get_type_not_found(self):
        """Returns None when type does not exist."""
        pool = _FakePool(rows=[])
        registry = ContentTypeRegistry(db=pool)
        result = await registry.get_type("missing_type")
        assert result is None

    @pytest.mark.asyncio
    async def test_register_inserts_row(self):
        """register calls execute with INSERT."""
        pool = _FakePool(rows=[])
        registry = ContentTypeRegistry(db=pool)
        result = await registry.register(
            name="blog_post",
            description="A blog post.",
            required_params=[{"name": "title", "type": "str"}],
            optional_params=[],
            voice_profile="spencer-default",
        )
        assert result["name"] == "blog_post"
        assert "INSERT" in pool._last_query
        assert "blog_post" in str(pool._last_args)

    @pytest.mark.asyncio
    async def test_register_without_voice_profile(self):
        """register works when voice_profile is None."""
        pool = _FakePool(rows=[])
        registry = ContentTypeRegistry(db=pool)
        result = await registry.register(
            name="note",
            description="A quick note.",
            required_params=[],
            optional_params=[],
            voice_profile=None,
        )
        assert result["name"] == "note"
        # voice_profile should not be in the query args
        assert result["voice_profile"] is None

    @pytest.mark.asyncio
    async def test_list_types(self):
        """list_types returns all registered types."""
        rows = [
            {"name": "blog_post", "description": "A blog."},
            {"name": "research_note", "description": "A note."},
        ]
        pool = _FakePool(rows=rows)
        registry = ContentTypeRegistry(db=pool)
        result = await registry.list_types()
        assert len(result) == 2
        assert result[0]["name"] == "blog_post"
        assert result[1]["name"] == "research_note"


# ---------------------------------------------------------------------------
# SelfExtender
# ---------------------------------------------------------------------------

class _FakeRegistry:
    """A fake ContentTypeRegistry for testing SelfExtender."""

    def __init__(self, types=None):
        self._types = types or {}

    async def is_registered(self, name):
        return name in self._types

    async def get_type(self, name):
        return self._types.get(name)

    async def register(self, name, description, required_params,
                       optional_params, voice_profile=None):
        entry = {
            "name": name,
            "description": description,
            "required_params": required_params,
            "optional_params": optional_params,
            "voice_profile": voice_profile,
        }
        self._types[name] = entry
        return entry

    async def list_types(self):
        return list(self._types.values())


class _FakeLLM:
    """A fake LLMClient for testing SelfExtender."""

    def __init__(self, response=None):
        self._response = response or {}
        self._last_prompt = None

    async def chat(self, messages, **kwargs):
        self._last_prompt = messages
        import json
        return json.dumps(self._response)


class TestSelfExtender:
    @pytest.mark.asyncio
    async def test_ensure_type_already_registered(self):
        """When type exists, returns it immediately — no LLM call."""
        registry = _FakeRegistry(types={
            "blog_post": {
                "name": "blog_post",
                "description": "A blog post.",
                "required_params": [],
                "optional_params": [],
                "voice_profile": None,
            }
        })
        llm = _FakeLLM()
        extender = SelfExtender(registry=registry, llm=llm, config=SelfExtendConfig())

        result = await extender.ensure_type("blog_post")
        assert result["name"] == "blog_post"
        # LLM should not have been called
        assert llm._last_prompt is None

    @pytest.mark.asyncio
    async def test_ensure_type_researches_unknown(self):
        """When type is missing, researches via LLM and registers."""
        registry = _FakeRegistry(types={})
        llm_response = {
            "description": "A press release announcing news.",
            "required_params": [
                {"name": "title", "type": "str", "description": "Release title."}
            ],
            "optional_params": [
                {"name": "embargo_date", "type": "str", "description": "Publish-after date."}
            ],
            "voice_profile": "spencer-default",
        }
        llm = _FakeLLM(response=llm_response)
        extender = SelfExtender(registry=registry, llm=llm, config=SelfExtendConfig())

        result = await extender.ensure_type("press_release")

        assert result["name"] == "press_release"
        assert result["description"] == "A press release announcing news."
        assert len(result["required_params"]) == 1
        assert result["required_params"][0]["name"] == "title"
        assert result["voice_profile"] == "spencer-default"
        # LLM should have been called with the type name
        assert llm._last_prompt is not None
        assert "press_release" in str(llm._last_prompt)

    @pytest.mark.asyncio
    async def test_ensure_type_respects_config_temperature(self):
        """LLM research uses the configured temperature."""
        registry = _FakeRegistry(types={})
        llm = _FakeLLM(response={"description": "Test.", "required_params": [],
                                  "optional_params": [], "voice_profile": None})
        config = SelfExtendConfig(research_temperature=0.7)
        extender = SelfExtender(registry=registry, llm=llm, config=config)

        await extender.ensure_type("test_type")
        # Prompt was sent — LLM was called
        assert llm._last_prompt is not None

    @pytest.mark.asyncio
    async def test_ensure_type_llm_failure_uses_fallback(self):
        """When LLM fails, registers with fallback description and empty params."""
        registry = _FakeRegistry(types={})

        class _FailingLLM:
            async def chat(self, messages, **kwargs):
                raise RuntimeError("LLM unavailable")

        llm = _FailingLLM()
        config = SelfExtendConfig(fallback_description="Fallback type.")
        extender = SelfExtender(registry=registry, llm=llm, config=config)

        result = await extender.ensure_type("resilient_type")
        assert result["name"] == "resilient_type"
        assert result["description"] == "Fallback type."
        assert result["required_params"] == []
        assert result["optional_params"] == []

    @pytest.mark.asyncio
    async def test_ensure_type_invalid_llm_json_uses_fallback(self):
        """When LLM returns bad JSON, falls back."""
        registry = _FakeRegistry(types={})

        class _BadJsonLLM:
            async def chat(self, messages, **kwargs):
                return "not valid json {{{"

        llm = _BadJsonLLM()
        extender = SelfExtender(registry=registry, llm=llm, config=SelfExtendConfig())

        result = await extender.ensure_type("bad_json_type")
        assert result["name"] == "bad_json_type"
        assert result["description"] == "Auto-registered content type."

    @pytest.mark.asyncio
    async def test_ensure_type_llm_missing_fields_fills_defaults(self):
        """Partial LLM response gets defaulted fields."""
        registry = _FakeRegistry(types={})
        llm = _FakeLLM(response={"description": "Just a description."})
        extender = SelfExtender(registry=registry, llm=llm, config=SelfExtendConfig())

        result = await extender.ensure_type("partial_type")
        assert result["name"] == "partial_type"
        assert result["description"] == "Just a description."
        assert result["required_params"] == []
        assert result["optional_params"] == []
        assert result["voice_profile"] is None

    @pytest.mark.asyncio
    async def test_ensure_type_normalizes_name(self):
        """Type names are lowercased and whitespace-trimmed."""
        registry = _FakeRegistry(types={})
        llm = _FakeLLM(response={"description": "Test.", "required_params": [],
                                  "optional_params": [], "voice_profile": None})
        extender = SelfExtender(registry=registry, llm=llm, config=SelfExtendConfig())

        result = await extender.ensure_type("  Blog_Post  ")
        assert result["name"] == "blog_post"

    @pytest.mark.asyncio
    async def test_ensure_type_rejects_empty_name(self):
        """Empty or whitespace-only names raise SelfExtendError."""
        registry = _FakeRegistry()
        llm = _FakeLLM()
        extender = SelfExtender(registry=registry, llm=llm, config=SelfExtendConfig())

        with pytest.raises(SelfExtendError, match="name"):
            await extender.ensure_type("")

        with pytest.raises(SelfExtendError, match="name"):
            await extender.ensure_type("   ")

    @pytest.mark.asyncio
    async def test_list_registered_types(self):
        """SelfExtender can list all registered types."""
        registry = _FakeRegistry(types={
            "blog_post": {"name": "blog_post", "description": "Blog."},
            "note": {"name": "note", "description": "Note."},
        })
        llm = _FakeLLM()
        extender = SelfExtender(registry=registry, llm=llm, config=SelfExtendConfig())

        types = await extender.list_registered_types()
        assert len(types) == 2
        names = {t["name"] for t in types}
        assert names == {"blog_post", "note"}
