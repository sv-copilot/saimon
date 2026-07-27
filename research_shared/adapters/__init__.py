"""adapters — shadow library source index adapters.

Each adapter implements the SourceIndexAdapter protocol and connects
to a specific shadow library: Anna's Archive, LibGen, Sci-Hub, Internet
Archive, Academic Torrents.
"""

from research_shared.adapters.base import SourceIndexAdapter, SourceSearchResult

__all__ = ["SourceIndexAdapter", "SourceSearchResult"]
