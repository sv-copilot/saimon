"""sources.py — the composition point: which source adapters this deployment searches.

Every decision about *which* sources exist lives here and nowhere else. Services
ask the registry for adapters; they never name one, so swapping the source set is
a change to this file rather than a change scattered across the services.

`DEFAULT_SOURCE_INDEXES` is the set a search query uses when the caller does not
name one. It is deliberately explicit rather than "everything registered": an
adapter being available is not the same as it being appropriate for every query.

Deployments differ. A deployment that searches only openly available sources
registers only those; a deployment with access to further sources registers them
here, in its own tree, with its own credentials. This module is the seam.
"""

from __future__ import annotations

from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter
from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.libgen import LibGenAdapter
from research_shared.adapters.scihub import SciHubAdapter

#: Sources a query searches when it does not name any. Academic Torrents is
#: registered but not searched by default: it returns whole datasets rather than
#: the individual works a normal query is looking for.
DEFAULT_SOURCE_INDEXES = frozenset(
    {
        "annas_archive",
        "libgen",
        "scihub",
        "internet_archive",
    }
)


def compose_registry(registry) -> None:
    """Register this deployment's adapters into *registry*.

    Called once, lazily, by ``research_shared.source_registry.get_registry``.
    """
    registry.register_all(
        [
            AnnasArchiveAdapter(),
            LibGenAdapter(),
            SciHubAdapter(),
            InternetArchiveAdapter(),
            AcademicTorrentsAdapter(),
        ]
    )


def default_source_indexes() -> frozenset[str]:
    """Sources searched when the caller names none."""
    return DEFAULT_SOURCE_INDEXES
