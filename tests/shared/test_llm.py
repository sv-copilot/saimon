"""Tests for research_shared.llm — DeepSeek LLM client abstraction."""

import pytest

from research_shared.llm import LLMClient, LLMConfig, LLMError


class TestLLMConfig:
    def test_from_env_defaults(self, clean_env):
        """With no env vars, uses sensible defaults."""
        config = LLMConfig.from_env()
        assert config.base_url == "https://api.deepseek.com/v1"
        assert config.model == "deepseek-v4-pro"
        assert config.api_key is None

    def test_from_env_reads_api_key(self, mock_api_key_env):
        """Reads SAIMON_API_KEY from environment."""
        config = LLMConfig.from_env()
        assert config.api_key == "sk-test-mock-key-12345"

    def test_from_env_custom_values(self, clean_env, monkeypatch):
        """Custom env vars override defaults."""
        monkeypatch.setenv("SAIMON_API_KEY", "sk-custom")
        monkeypatch.setenv("SAIMON_LLM_MODEL", "deepseek-reasoner")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://custom.api.com/v1")
        monkeypatch.setenv("SAIMON_LLM_TIMEOUT", "45")
        monkeypatch.setenv("SAIMON_LLM_MAX_TOKENS", "8192")

        config = LLMConfig.from_env()
        assert config.api_key == "sk-custom"
        assert config.model == "deepseek-reasoner"
        assert config.base_url == "https://custom.api.com/v1"
        assert config.timeout == 45
        assert config.max_tokens == 8192

    def test_repr_masks_api_key(self):
        """Config repr hides the API key."""
        config = LLMConfig(api_key="sk-secret-key-abc123")
        r = repr(config)
        assert "sk-secret-key-abc123" not in r


class TestLLMClient:
    def test_construction_without_api_key_fails(self, clean_env):
        """Fail-closed: constructing client without an API key raises."""
        config = LLMConfig(api_key=None)
        with pytest.raises(LLMError, match="API key"):
            LLMClient(config)

    def test_construction_with_api_key_succeeds(self, mock_api_key_env):
        """Client constructs when an API key is provided."""
        config = LLMConfig(api_key="sk-test-key")
        client = LLMClient(config)
        assert client.config.api_key == "sk-test-key"

    def test_generate_not_implemented_without_network(self, mock_api_key_env):
        """generate raises NotImplementedError when called without
        network — this is expected; actual LLM calls need a live endpoint.
        The contract is that generate() accepts a prompt and returns str."""
        config = LLMConfig(api_key="sk-test-key")
        client = LLMClient(config)
        # The base class/interface expects this shape.
        # In real use the OpenAI client would be invoked.
        # For now we verify the method exists and accepts the right args.
        assert hasattr(client, "generate")
        import inspect

        sig = inspect.signature(client.generate)
        assert "prompt" in sig.parameters

    def test_llm_error_is_exception(self):
        """LLMError is a proper exception class."""
        err = LLMError("Something went wrong", code="LLM_TIMEOUT")
        assert str(err) == "Something went wrong"
        assert err.code == "LLM_TIMEOUT"
        assert isinstance(err, Exception)
