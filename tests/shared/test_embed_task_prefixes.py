"""Task prefixes: documents and queries must embed the way the model was trained.

nomic-embed-text-v1.5 expects `search_document: ` for corpus text and
`search_query: ` for queries. The repo contained neither string, so both sides
were embedded identically and the contrastive training was wasted.

The flag defaults OFF: the shipped corpus was embedded without prefixes, so
turning this on before a re-embed would place queries and documents in different
spaces. #260 flips it together with the re-ingest.
"""

from __future__ import annotations

import pytest

from research_shared.embedding import (
    DOCUMENT_PREFIX,
    QUERY_PREFIX,
    document_embed_text,
    embed_node_text,
    query_embed_text,
    task_prefixes_enabled,
)


@pytest.fixture
def prefixed(monkeypatch):
    monkeypatch.setenv("SAIMON_EMBED_TASK_PREFIXES", "1")
    yield
    monkeypatch.delenv("SAIMON_EMBED_TASK_PREFIXES", raising=False)


@pytest.fixture
def unprefixed(monkeypatch):
    monkeypatch.delenv("SAIMON_EMBED_TASK_PREFIXES", raising=False)


class TestFlag:
    def test_default_is_off(self, unprefixed):
        assert task_prefixes_enabled() is False

    def test_on_values(self, monkeypatch):
        for value in ("1", "true", "yes", "on"):
            monkeypatch.setenv("SAIMON_EMBED_TASK_PREFIXES", value)
            assert task_prefixes_enabled() is True
        for value in ("0", "false", "no", ""):
            monkeypatch.setenv("SAIMON_EMBED_TASK_PREFIXES", value)
            assert task_prefixes_enabled() is False


class TestBuilders:
    def test_document_prefix(self, prefixed):
        assert document_embed_text("  body text  ") == f"{DOCUMENT_PREFIX}body text"

    def test_query_prefix(self, prefixed):
        assert query_embed_text(" how do I reset it ") == f"{QUERY_PREFIX}how do I reset it"

    def test_off_is_byte_identical_to_raw_text(self, unprefixed):
        assert document_embed_text("body text") == "body text"
        assert query_embed_text("query text") == "query text"

    def test_document_cap_is_applied_before_prefixing(self, prefixed):
        out = document_embed_text("x" * 9000, max_chars=100)
        assert out == DOCUMENT_PREFIX + "x" * 100

    def test_node_text_uses_document_prefix_when_on(self, prefixed):
        # embed_node_text returns a vector; assert on the text it would embed by
        # monkeypatching embed_local's input capture instead.
        import research_shared.embedding as emb

        seen: list[str] = []
        original = emb.embed_local

        def capture(text, *args, **kwargs):
            seen.append(text)

        emb.embed_local = capture
        try:
            embed_node_text("A Title", "body text")
        finally:
            emb.embed_local = original
        assert seen == [f"{DOCUMENT_PREFIX}body text"]

    def test_node_text_unchanged_when_off(self, unprefixed):
        import research_shared.embedding as emb

        seen: list[str] = []
        original = emb.embed_local

        def capture(text, *args, **kwargs):
            seen.append(text)

        emb.embed_local = capture
        try:
            embed_node_text("A Title", "body text")
        finally:
            emb.embed_local = original
        assert seen == ["A Title\nbody text"]


class TestRerankPassageSplit:
    def test_query_and_passage_use_different_embedders(self):
        from research_shared.rerank import RerankConfig, rerank

        used: list[tuple[str, str]] = []

        def query_embed(text):
            used.append(("query", text))
            return [1.0, 0.0]

        def passage_embed(text):
            used.append(("passage", text))
            return [1.0, 0.0]

        rerank(
            "hnsw index",
            [{"id": "1", "body": "hnsw index parameters", "similarity": None},
             {"id": "2", "body": "unrelated text", "similarity": None}],
            RerankConfig(),
            embed_fn=query_embed,
            passage_embed_fn=passage_embed,
        )
        kinds = {kind for kind, _ in used}
        assert kinds == {"query", "passage"}
        assert sum(1 for kind, _ in used if kind == "query") == 1
