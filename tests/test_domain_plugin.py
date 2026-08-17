"""Tests for research_shared.domain_plugin — the domain plugin contract.

The domain plugin interface is the open-source (MIT) boundary every domain
plugin implements against.  These tests pin the contract: ``DomainTool`` is a
runtime-checkable structural protocol, ``DomainPlugin`` is an ABC whose
optional members default to empty collections.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from research_shared.domain_plugin import DomainPlugin, DomainTool


class FakeTool:
    """A minimal structural DomainTool — no subclassing required."""

    name = "fake_tool"
    description = "A fake domain tool used in tests."
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "arguments": arguments}


class NotATool:
    """Missing the execute member — must not match the protocol."""

    name = "not_a_tool"
    description = "nope"
    input_schema: ClassVar[dict[str, Any]] = {}


class FakePlugin(DomainPlugin):
    """A minimal plugin implementing only the abstract members."""

    domain = "example"

    def adapters(self) -> list:
        return []

    def content_types(self) -> list:
        return []

    def tools(self) -> list:
        return [FakeTool()]


class TestDomainToolProtocol:
    def test_is_runtime_checkable(self):
        """DomainTool is declared runtime_checkable."""
        assert getattr(DomainTool, "_is_runtime_protocol", False) is True

    def test_instance_matches_structurally(self):
        """An object with the four members is a DomainTool."""
        assert isinstance(FakeTool(), DomainTool)

    def test_subclass_matches_structurally(self):
        """A class with the four members is a DomainTool subclass."""
        assert issubclass(FakeTool, DomainTool)

    def test_missing_member_does_not_match(self):
        """A class missing execute() is not a DomainTool."""
        assert not isinstance(NotATool(), DomainTool)


class TestDomainPluginABC:
    def test_cannot_instantiate_base(self):
        """DomainPlugin is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            DomainPlugin()

    def test_minimal_plugin_instantiates(self):
        """A plugin implementing only abstract members is concrete."""
        plugin = FakePlugin()
        assert isinstance(plugin, DomainPlugin)

    def test_abstract_members(self):
        """All abstract members are required and provided by the fake."""
        plugin = FakePlugin()
        assert plugin.domain == "example"
        assert plugin.adapters() == []
        assert plugin.content_types() == []
        tools = plugin.tools()
        assert len(tools) == 1
        assert isinstance(tools[0], DomainTool)

    def test_schema_migrations_defaults_to_empty(self):
        """Optional schema_migrations() defaults to an empty list."""
        assert FakePlugin().schema_migrations() == []

    def test_weighting_models_defaults_to_empty(self):
        """Optional weighting_models() defaults to an empty dict."""
        assert FakePlugin().weighting_models() == {}


class TestToolExecution:
    async def test_execute_returns_result(self):
        """A concrete tool's execute returns a dict result."""
        tool = FakeTool()
        result = await tool.execute({"x": 1})
        assert result == {"ok": True, "arguments": {"x": 1}}


class TestPackageExports:
    def test_exported_from_package(self):
        """DomainPlugin and DomainTool are re-exported from research_shared."""
        from research_shared import DomainPlugin as PkgPlugin
        from research_shared import DomainTool as PkgTool

        assert PkgPlugin is DomainPlugin
        assert PkgTool is DomainTool
