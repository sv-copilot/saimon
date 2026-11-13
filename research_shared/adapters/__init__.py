"""Source-index adapters.

Each adapter implements the SourceIndexAdapter protocol for one lawful public
archive. The only adapter shipped is Internet Archive; the project deliberately
does not include scrapers for Sci-Hub, LibGen or Anna's Archive.

The module name `adapters` is historical. Earlier development called these
"shadow libraries"; that surface has been removed (see README, "Scope and
limitations").
"""

from research_shared.adapters.base import SourceIndexAdapter, SourceSearchResult
from research_shared.adapters.internet_archive import InternetArchiveAdapter

__all__ = [
    "InternetArchiveAdapter",
    "SourceIndexAdapter",
    "SourceSearchResult",
]
