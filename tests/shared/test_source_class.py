"""Source classification must cope with the URLs the corpus actually stores."""

from __future__ import annotations

import pytest

from research_shared.primacy import source_class_from_host


@pytest.mark.parametrize(
    "value,expected",
    [
        ("arxiv.org", "journal_article"),
        ("url:https://arxiv.org/pdf/2005.11401", "journal_article"),
        ("https://www.census.gov/library/stories/2026/05/x.html", "government_report"),
        ("url:https://advocacy.sba.gov/wp-content/uploads/x.pdf", "government_report"),
        ("https://www.w3.org/TR/prov-o/", "report"),
        ("https://en.wikipedia.org/wiki/Bicycle", "report"),
        ("https://docs.n8n.io/hosting/scaling/queue-mode", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_source_class(value, expected):
    assert source_class_from_host(value) == expected
