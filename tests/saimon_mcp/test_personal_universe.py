"""Personal universe: write ownership and read refusal (#269).

A private universe must be unreadable without an owner and unwritable without
one. The dangerous failure is silent: falling back to reality makes a refused
private query look like a successful public one.
"""

from __future__ import annotations

import asyncio

from saimon_mcp.generate import server as generate_server
from saimon_mcp.search import server as search_server


def _universes():
    return [
        {"id": "u-reality", "slug": "reality", "parent_id": None, "visibility": "public"},
        {"id": "u-personal", "slug": "personal", "parent_id": None, "visibility": "private"},
    ]


class _Pool:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def fetch(self, sql, *params):
        if "FROM universes" in sql:
            return _universes()
        return self._rows


class TestWriteOwnership:
    def test_public_universe_writes_without_owner(self, monkeypatch):
        monkeypatch.setattr(generate_server, "_db_pool", _Pool())
        universe_id, refusal = asyncio.run(
            generate_server._resolve_universe_for_write("reality", None)
        )
        assert universe_id == "u-reality" and refusal is None

    def test_private_universe_requires_an_owner(self, monkeypatch):
        monkeypatch.setattr(generate_server, "_db_pool", _Pool())
        universe_id, refusal = asyncio.run(
            generate_server._resolve_universe_for_write("personal", None)
        )
        assert universe_id is None
        assert refusal == "private_universe_requires_owner"

    def test_private_universe_accepts_an_owner(self, monkeypatch):
        monkeypatch.setattr(generate_server, "_db_pool", _Pool())
        universe_id, refusal = asyncio.run(
            generate_server._resolve_universe_for_write("personal", "user-1")
        )
        assert universe_id == "u-personal" and refusal is None

    def test_unknown_universe_is_refused(self, monkeypatch):
        monkeypatch.setattr(generate_server, "_db_pool", _Pool())
        _, refusal = asyncio.run(
            generate_server._resolve_universe_for_write("atlantis", "user-1")
        )
        assert refusal == "unknown_universe:atlantis"


class TestReadRefusal:
    def test_private_without_owner_returns_an_empty_scope(self, monkeypatch):
        monkeypatch.setattr(search_server, "_db_pool", _Pool())
        scope = asyncio.run(search_server._resolve_universe({"universe": "personal"}))
        assert scope == []

    def test_private_with_owner_resolves(self, monkeypatch):
        monkeypatch.setattr(search_server, "_db_pool", _Pool())
        scope = asyncio.run(
            search_server._resolve_universe({"universe": "personal", "user_id": "user-1"})
        )
        assert scope == ["u-personal"]

    def test_public_universe_needs_no_owner(self, monkeypatch):
        monkeypatch.setattr(search_server, "_db_pool", _Pool())
        scope = asyncio.run(search_server._resolve_universe({"universe": "reality"}))
        assert scope == ["u-reality"]

    def test_default_is_reality_not_everything(self, monkeypatch):
        monkeypatch.setattr(search_server, "_db_pool", _Pool())
        assert asyncio.run(search_server._resolve_universe({})) == ["u-reality"]

    def test_explicit_star_is_unrestricted(self, monkeypatch):
        monkeypatch.setattr(search_server, "_db_pool", _Pool())
        assert asyncio.run(search_server._resolve_universe({"universe": "*"})) is None

    def test_empty_scope_does_not_fall_back_to_everything(self, monkeypatch):
        """The refusal must survive the empty list, not be treated as 'no filter'."""
        pool = _Pool([{"id": "x", "universe_id": "u-reality"}])
        monkeypatch.setattr(search_server, "_db_pool", pool)
        rows = asyncio.run(search_server._keyword_search("rate", 10, None, []))
        assert rows == []
