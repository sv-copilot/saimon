"""Ingest fetch presentation: browser identity by default, env override.

A self-identifying bot UA is refused (403/405) by a large share of .gov/.edu and
trade-association hosts, which silently removes whole categories from the
corpus. The fetcher therefore presents a browser identity for public URLs the
caller supplied, and the identity stays overridable for hosts that want a
contactable agent string.
"""

from __future__ import annotations

from saimon_mcp.search.server import BROWSER_UA, _ingest_headers


class TestIngestHeaders:
    def test_defaults_to_a_browser_identity(self):
        headers = _ingest_headers()
        assert headers["User-Agent"] == BROWSER_UA
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert "text/html" in headers["Accept"]
        assert "pdf" in headers["Accept"]

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("SAIMON_INGEST_USER_AGENT", "saimon-ingest/2.0 (+contact)")
        assert _ingest_headers()["User-Agent"] == "saimon-ingest/2.0 (+contact)"

    def test_headers_are_fresh_copies(self, monkeypatch):
        first = _ingest_headers()
        first["User-Agent"] = "mutated"
        assert _ingest_headers()["User-Agent"] != "mutated"
