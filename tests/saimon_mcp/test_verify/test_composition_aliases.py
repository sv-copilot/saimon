"""Tests for the composition aliases: retired names a deployment still serves.

The rename from source-specific vocabulary to source-agnostic vocabulary must not
break a deployment's existing callers, and it must not change what a *default*
request does. Both halves of that promise are pinned here.
"""

import pathlib
import re

import pytest

from research_shared.sources import (
    evidence_type_source_index,
    method_aliases,
    param_aliases,
)

from saimon_mcp.verify import server as verify_server


class TestParameterAliases:
    def test_canonical_name_is_read(self):
        assert verify_server._param_flag({"use_source_search": True}, "use_source_search") is True

    def test_retired_name_is_still_accepted(self):
        """A caller that has not been updated keeps working."""
        for retired in param_aliases().get("use_source_search", ()):
            assert verify_server._param_flag({retired: True}, "use_source_search") is True

    def test_canonical_wins_when_both_are_present(self):
        aliases = param_aliases().get("use_source_search", ())
        if not aliases:
            pytest.skip("this deployment declares no retired parameter names")
        params = {"use_source_search": False, aliases[0]: True}
        assert verify_server._param_flag(params, "use_source_search") is False

    def test_absent_flag_is_false(self):
        assert verify_server._param_flag({}, "use_source_search") is False


class TestMethodAliases:
    def test_a_default_request_runs_only_canonical_methods(self):
        """An alias must never change what a default request does.

        Regression guard: registering a retired method id into the method table
        put it in the default set, where no verifier existed for it.
        """
        retired = set(method_aliases().values())
        defaults = set(verify_server._canonical_method_names())
        assert defaults, "a default request would run no methods at all"
        assert not (defaults & retired), f"retired ids leaked into the default set: {defaults & retired}"

    def test_a_retired_method_id_is_still_servable(self):
        for canonical, retired in method_aliases().items():
            assert retired in verify_server._METHODS
            assert verify_server._METHODS[retired]["name"] == retired
            # the retired entry tells a reader which id replaced it
            assert canonical in verify_server._METHODS[retired]["description"]


class TestTheRenameDidNotCollide:
    """The renamed method must not have taken over an existing method id.

    The first attempt at this rename chose `source_corroboration` as the new id,
    which already belonged to a different method (corroboration against sources
    the caller supplies). Registering over it changed that method's description
    and reliability, and the duplicate key in the stub table silently dropped its
    entry. Nothing failed, because nothing asserted the old method still existed.
    """

    def test_the_pre_existing_method_is_untouched(self):
        entry = verify_server._METHODS["source_corroboration"]
        assert entry["description"] == "Cross-reference the claim against known sources."
        assert entry["reliability"] == 0.85

    def test_the_renamed_method_is_a_distinct_id(self):
        mine = verify_server._METHODS["source_index_corroboration"]
        assert mine["name"] == "source_index_corroboration"
        assert mine is not verify_server._METHODS["source_corroboration"]

    def test_every_method_id_is_unique(self):
        """A repeated key in the method table silently drops an entry."""
        source = pathlib.Path(verify_server.__file__).read_text(encoding="utf-8")
        keys = re.findall(r'^\s{8}"([a-z_]+)": \{$', source, re.M)
        duplicates = {k for k in keys if keys.count(k) > 1}
        assert not duplicates, f"duplicate method keys in the stub table: {sorted(duplicates)}"


class TestStoredValues:
    def test_evidence_type_is_a_declared_value(self):
        """The stored evidence_type comes from the deployment, not from code."""
        assert isinstance(evidence_type_source_index(), str)
        assert evidence_type_source_index()
