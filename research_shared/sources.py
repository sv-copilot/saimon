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

from research_shared.adapters.academic_torrents import AcademicTorrentsAdapter
from research_shared.adapters.annas_archive import AnnasArchiveAdapter
from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.libgen import LibGenAdapter
from research_shared.adapters.ranking import RankingPolicy
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


#: Which sources this deployment trusts most when ranking aggregated results.
#: Whole-work indexes rank above the broad digital library, whose title-match
#: noise is real (SAIMON-SEARCH-RELIABILITY-1, #201): news items, archive dumps
#: and repository pages that a citation cannot be verified against.
RANKING_POLICY = RankingPolicy(
    preferred_sources=frozenset({"annas_archive", "libgen", "scihub"}),
    deprioritised_sources=frozenset({"internet_archive"}),
)


def ranking_policy() -> RankingPolicy:
    """How this deployment weights sources when ranking results."""
    return RANKING_POLICY


#: Environment variables checked, first one set wins, to decide whether source
#: retrieval happens at all. The generic name comes first so a deployment can
#: move to it without a flag day.
SOURCES_ENABLED_ENV_VARS = ("RESEARCH_SOURCES_ENABLED", "SHADOW_SOURCES_ENABLED")


def sources_enabled_env_vars() -> tuple[str, ...]:
    """Environment variables that switch source retrieval on or off."""
    return SOURCES_ENABLED_ENV_VARS


#: Table holding fetched full text keyed by DOI. A deployment migrating from an
#: earlier table name sets SAIMON_FULLTEXT_CACHE_TABLE, or changes this default
#: in its own composition.
FULLTEXT_CACHE_TABLE_DEFAULT = "shadow_sources_cache"


def fulltext_cache_table() -> str:
    """Name of the full-text cache table for this deployment."""
    import os

    return os.environ.get("SAIMON_FULLTEXT_CACHE_TABLE", FULLTEXT_CACHE_TABLE_DEFAULT)


#: Tool names kept working for clients that predate a rename. Keyed by the
#: current name, valued by the retired names this deployment still answers to.
LEGACY_TOOL_ALIASES = {"search_sources": ("search_shadow_libraries",)}


def legacy_tool_aliases() -> dict[str, tuple[str, ...]]:
    """Retired tool names this deployment still answers to."""
    return LEGACY_TOOL_ALIASES


#: Retired request parameters this deployment still accepts: canonical -> retired.
#: A fresh deployment declares none and accepts only the canonical name.
PARAM_ALIASES = {"use_source_search": ("use_shadow_sources",)}

#: Verification method ids: canonical -> retired. Both are registered while the
#: retired id is still in use.
METHOD_ALIASES = {"source_index_corroboration": "shadow_source_corroboration"}

#: ``evidence_type`` written for evidence backed by a source index. This is a
#: stored value, so a deployment with existing rows keeps its own.
EVIDENCE_TYPE_SOURCE_INDEX = "shadow_source"


def param_aliases() -> dict[str, tuple[str, ...]]:
    """Retired request parameter names this deployment still accepts."""
    return PARAM_ALIASES


def method_aliases() -> dict[str, str]:
    """Retired verification method ids this deployment still serves."""
    return METHOD_ALIASES


def evidence_type_source_index() -> str:
    """``evidence_type`` stored for source-index evidence."""
    return EVIDENCE_TYPE_SOURCE_INDEX


#: Sources this deployment consents to fetching full text from, unless the
#: FULLTEXT_DOWNLOAD_CONSENT environment variable narrows it. This is a
#: deployment decision with consequences, which is why it is declared here and
#: not defaulted in the service: fetching from a source you have no right to was
#: never a thing this platform should do quietly.
FULLTEXT_CONSENT_DEFAULT = frozenset(
    {
        "annas_archive",
        "libgen",
        "scihub",
        "internet_archive",
        "academic_torrents",
    }
)

#: Source a DOI-only request resolves against when nothing else identifies one.
DEFAULT_DOI_SOURCE = "scihub"


def fulltext_consent_default() -> frozenset[str]:
    """Sources this deployment consents to fetch full text from."""
    return FULLTEXT_CONSENT_DEFAULT


def default_doi_source() -> str:
    """Source used to resolve a bare DOI."""
    return DEFAULT_DOI_SOURCE


#: Which sources this deployment counts as tier A / B / C when scoring how much
#: weight a piece of evidence deserves. A judgement about sources, so it is
#: declared here: a deployment with different sources declares different tiers,
#: or none, and then citation counts alone decide.
SOURCE_TIER_INDEXES = {
    "A": frozenset({"scihub", "pubmed", "crossref", "scopus", "wos"}),
    "B": frozenset({"libgen", "semantic_scholar", "dblp", "ieee"}),
    "C": frozenset({"arxiv", "ssrn", "researchgate", "preprint"}),
}


def source_tier_indexes() -> dict[str, frozenset[str]]:
    """This deployment's tier classification of sources."""
    return SOURCE_TIER_INDEXES
