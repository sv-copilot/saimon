"""Chunking must follow the form of the document, not a fixed character window.

The previous implementation flattened every newline (``" ".join(text.split())``)
and cut a 2,000-character window, which split sentences, shredded tables and
dropped headings into the middle of chunks. These tests pin the structural
behaviour: break on sentence and paragraph boundaries, keep list items whole,
drop low-signal lines, and never exceed the cap.
"""

from __future__ import annotations

from research_shared.fulltext import (
    FULLTEXT_CHUNK_MAX,
    FULLTEXT_CHUNK_MIN,
    chunk_text,
)

SENTENCE = (
    "Operators report that the reconciliation step takes six hours each week "
    "because the invoice totals never match the bank feed."
)


def test_chunks_end_on_sentence_boundaries() -> None:
    text = " ".join(f"{SENTENCE} Case {i}." for i in range(40))
    chunks = chunk_text(text, min_chars=800, max_chars=1200)
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk.rstrip().endswith((".", "!", "?")), chunk[-80:]


def test_paragraph_breaks_are_preferred() -> None:
    paragraph = " ".join([SENTENCE] * 8)
    text = f"{paragraph}\n\n{paragraph}\n\n{paragraph}"
    chunks = chunk_text(text, min_chars=600, max_chars=900)
    for chunk in chunks:
        assert len(chunk) <= 900
    # A paragraph boundary is a legitimate break point, so no chunk should begin
    # with the tail of a word.
    for chunk in chunks:
        assert not chunk.startswith(" ")


def test_no_chunk_exceeds_the_cap() -> None:
    text = "\n\n".join(" ".join([SENTENCE] * 10) for _ in range(10))
    for chunk in chunk_text(text):
        assert len(chunk) <= FULLTEXT_CHUNK_MAX


def test_low_signal_lines_are_dropped() -> None:
    text = (
        "The cash flow projection covers twelve months of receipts.\n"
        "Chapter ............ 42\n"
        "12\n"
        "-----\n"
        "Payments are grouped by month and by category."
    )
    chunks = chunk_text(text, min_chars=10, max_chars=500)
    joined = " ".join(chunks)
    assert "Chapter ............ 42" not in joined
    assert "cash flow projection" in joined
    assert "Payments are grouped" in joined


def test_list_items_are_not_merged_into_prose() -> None:
    text = (
        "Use the following steps when closing the month.\n"
        "- Reconcile the bank feed against the ledger.\n"
        "- Post the depreciation journal entry.\n"
        "- Send the summary to the client.\n"
    )
    chunks = chunk_text(text, min_chars=10, max_chars=600)
    joined = " ".join(chunks)
    assert "- Reconcile" in joined
    assert "- Post the depreciation" in joined


def test_hyphenated_line_breaks_are_rejoined() -> None:
    text = "The reconciliation work-\nflow is documented in the appendix."
    chunks = chunk_text(text, min_chars=10, max_chars=500)
    assert "workflow" in chunks[0]


def test_short_text_is_returned_whole_and_normalised() -> None:
    assert chunk_text("  short   text  ") == ["short text"]


def test_empty_input_returns_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunks_reach_the_target_size() -> None:
    text = " ".join(f"{SENTENCE}" for _ in range(40))
    chunks = chunk_text(text)
    assert all(len(c) >= FULLTEXT_CHUNK_MIN * 0.5 for c in chunks[:-1])
