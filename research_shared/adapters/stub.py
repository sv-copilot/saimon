"""stub.py — a source adapter that needs nothing.

Every other adapter needs something: a network, an account, an entitlement, a
running service. This one needs nothing, which is what makes the whole platform
runnable on a laptop with no credentials and testable in CI with no network.

It is not a mock in the test sense — it is a first-class adapter you can register
alongside real ones. A deployment can use it to:

- prove an installation works end to end before configuring any real source
- run the test suite and the eval harness offline
- develop the services, the ranking and the pipeline without touching a network

Results are deterministic: the same query always yields the same identifiers, so
assertions and fixtures stay stable. The identifiers are synthetic and carry no
meaning; nothing here fetches anything.
"""

from __future__ import annotations

import hashlib

from research_shared.adapters.base import FulltextFetchResult, SourceSearchResult

#: How many results a stub query returns. Small on purpose: enough to exercise
#: ranking, dedup and the response envelope, not enough to pretend to be a
#: corpus.
DEFAULT_RESULT_COUNT = 3


def _digest(text: str, length: int = 12) -> str:
    """A short, stable hex digest of *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


class StubAdapter:
    """A deterministic, offline source adapter.

    Satisfies :class:`research_shared.adapters.base.SourceIndexAdapter`. Declares
    ``access = "local"`` because it reaches nothing outside the process.
    """

    name: str = "stub"
    tier: str = "C"
    trust_model: str = "algorithmic"
    label: str = "Stub (offline, synthetic)"
    kind: str = "mixed"
    access: str = "local"

    def __init__(self, result_count: int = DEFAULT_RESULT_COUNT) -> None:
        self.result_count = result_count

    async def search(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> list[SourceSearchResult]:
        """Return deterministic synthetic results for *query*.

        Honours ``limit`` and ``offset`` the same way a real adapter would, so
        paging code can be exercised against it.
        """
        available = max(0, self.result_count - offset)
        count = min(limit, available)
        results: list[SourceSearchResult] = []
        for index in range(count):
            ordinal = offset + index
            title = f"{query} (stub result {ordinal + 1})"
            results.append(
                SourceSearchResult(
                    type="academic_paper",
                    identifier=f"stub:{_digest(f'{query}:{ordinal}')}",
                    doi=f"10.0000/stub.{_digest(f'{query}:{ordinal}', 8)}",
                    title=title,
                    authors=["Stub Author"],
                    year=2000 + (ordinal % 25),
                    abstract_snippet=(
                        "Synthetic abstract produced without network access. "
                        "Not a real work."
                    ),
                    source_index=self.name,
                    source_index_label=self.label,
                    relevance_score=round(1.0 - (ordinal * 0.1), 2),
                    full_text_available=True,
                    file_type="txt",
                )
            )
        return results

    async def resolve_doi(self, doi: str) -> SourceSearchResult | None:
        """Resolve any DOI to a synthetic result, or None for an empty DOI."""
        if not doi or not doi.strip():
            return None
        return SourceSearchResult(
            type="academic_paper",
            identifier=f"stub:{_digest(doi)}",
            doi=doi,
            title=f"Stub record for {doi}",
            authors=["Stub Author"],
            source_index=self.name,
            source_index_label=self.label,
            relevance_score=1.0,
            full_text_available=True,
            file_type="txt",
        )

    async def fetch_fulltext(
        self, result: SourceSearchResult
    ) -> FulltextFetchResult | None:
        """Return synthetic bytes for *result*.

        Deterministic, so a test can assert on the content hash.
        """
        body = (
            f"Stub full text for {result.identifier}\n"
            f"Title: {result.title}\n"
            "This content is generated locally and is not a real publication.\n"
        )
        return FulltextFetchResult(
            source_index=self.name,
            doi=result.doi,
            data=body.encode("utf-8"),
            file_type="txt",
        )
