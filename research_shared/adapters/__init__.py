"""adapters — shadow library source index adapters.

Each adapter implements the SourceIndexAdapter protocol and connects
to a specific shadow library: Anna's Archive, LibGen, Sci-Hub, Internet
Archive, Academic Torrents.
"""

from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter
from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.base import SourceIndexAdapter, SourceSearchResult
from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.libgen import LibGenAdapter
from research_shared.adapters.scihub import SciHubAdapter

__all__ = [
    "AcademicTorrentsAdapter",
    "AnnasArchiveAdapter",
    "InternetArchiveAdapter",
    "LibGenAdapter",
    "SciHubAdapter",
    "SourceIndexAdapter",
    "SourceSearchResult",
]
