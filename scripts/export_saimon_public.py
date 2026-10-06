#!/usr/bin/env python3
"""Export the public Saimon tree from the private repository.

Design rules, learned the hard way on the Drake public/private split:

1. **Default deny.** A path ships only if this script allowlists it. A new file in
   the private tree does not leak because someone forgot to add it to an exclude
   list -- it is simply not in the plan.
2. **One source of truth for the allowlist.** The list lives here, in code, not in a
   markdown manifest. Drake's manifest was an existence check that nothing parsed,
   which is how a destructive publish path went unnoticed for months.
3. **The interface is public; the sources are not.** `adapters/base.py` and the
   protocol are the contract an adopter codes against. Every adapter that retrieves
   from a shadow library stays private, and the public registry is *generated* here
   rather than copied, so the private registry stays the private tree's business.
4. **A file that must differ between private and public is generated, never
   hand-edited in both places.**
5. **The scrub gate is the guarantee.** After planning, every shipped text file is
   scanned for markers that must never appear in public. Any hit is a hard failure
   (exit 3) -- the export does not silently redact, because a silent redaction is a
   missing check.

Usage:
    python3 scripts/export_saimon_public.py                  # dry run: report the plan
    python3 scripts/export_saimon_public.py --output /tmp/saimon-public
    python3 scripts/export_saimon_public.py --explain libgen # why is X (not) shipping
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {
    ".md", ".py", ".sh", ".json", ".yml", ".yaml", ".toml", ".sql", ".txt",
    ".cfg", ".ini", ".example", ".in", ".js", ".ts", ".tsx",
}

# ---------------------------------------------------------------------------
# What ships. Directories are recursive; the excludes below are applied after.
# ---------------------------------------------------------------------------

INCLUDE_DIRS = [
    "saimon_mcp",
    "tools/saimon-mcp-proxy",   # the proxy is the adopter's client entry point          # the nine MCP services: the platform itself
    "research_shared",     # the shared library: db, llm, embedding, validation, ...
    "eval_harness",        # the eval gate and its metrics
    "plugins",             # domain plugins; `legal` is lawful-source work
    "fixtures",            # eval fixtures (52 KB total, no bulk content)
    "tests",               # the suite, minus the shadow-source tests
    "db",                  # role bootstrap
]

INCLUDE_FILES = [
    "Dockerfile",
    "docker-entrypoint.sh",
    "docker-compose.yml",       # copied, then scrubbed; validator decides
    "pyproject.toml",
    "requirements.txt",
    "conftest.py",
    "schema.sql",
    "openapi.json",
    ".gitignore",
    ".dockerignore",
]

# Scripts worth shipping: the ones that operate on a public adopter's own data.
INCLUDE_SCRIPTS = [
    "scripts/preflight.sh",
    "scripts/adoption_smoke.py",
    "scripts/validate_public_tree.py",
    "scripts/validate_openapi_spec.py",
    "scripts/backfill_embeddings.py",
    "scripts/reembed_nodes.py",
]

# ---------------------------------------------------------------------------
# What never ships, and why. Every entry here is deliberate.
# ---------------------------------------------------------------------------

# Shadow-library source adapters. Retaining these is the whole legal problem.
SHADOW_ADAPTERS = ("libgen", "scihub", "annas_archive", "academic_torrents")

EXCLUDE_REL_PATHS = {
    # shadow sources and the machinery that registers them
    "research_shared/adapters/libgen.py",
    "research_shared/adapters/scihub.py",
    "research_shared/adapters/annas_archive.py",
    "research_shared/adapters/academic_torrents.py",
    "research_shared/adapters/download.py",     # assembles shadow-library downloads
    "research_shared/shadow_registry.py",
    "tests/test_shadow_registry.py",
    # operator-only data and operations
    "research_shared/content_ops_seed.py",
    "research_shared/job_hunt_config.py",
    "scripts/seed_content_ops_kg.py",
    "scripts/content_ops_seed_manifest.json",
    "scripts/provision_metabase.sql",
    "scripts/purge_low_quality_fulltext.py",
    "scripts/bundle_embedding_model.py",
    "tools/backup-db.sh",
    "tools/restore-db.sh",
    # deployment: the operator's hosts, registries and runners
    "docker-compose.prod.yml",
    "docker-compose.staging.yml",
    "docker-compose.override.yml",
    ".github/workflows/ci.yml",
    "docs/staging.md",
    "docs/smoke-tests.md",
    # the composition point: the public artifact brings its own (generated)
    "research_shared/sources.py",
    # generated from the private file rather than shipped as-is
    "schema.sql",
    "docker-compose.yml",
    # the API contract is regenerated by the public CI, so the operator's copy
    # (which carries the private repo URL and the production host) never ships
    "openapi.json",
    # tests bound to sources this artifact does not have
    "tests/shared/test_adapters.py",
    "tests/shared/test_adapter_exports.py",
    "tests/shared/test_ranking.py",
    "tests/shared/test_dedup.py",
    "tests/shared/test_fetch_fulltext.py",
    "tests/shared/test_s3_storage.py",
    "tests/shared/test_db_schema.py",
    "tests/shared/test_sql_injection.py",
    "tests/test_pipeline.py",
    "tests/test_compose_tags.py",   # asserts this deployment's registry tags
    "tests/test_docker_packaging.py",  # asserts the prod compose file, which is not shipped
    "tests/test_branch_flow_agents_docs.py",  # requires AGENTS.md, which ships only with consent
    "tests/test_branch_flow_docs.py",  # same: asserts repo-level agent contract docs
    "tests/saimon_mcp/test_embedding_model_bundle.py",  # tests a withheld bundling script
    "tests/test_docker.py",  # asserts the prod compose, the private CI's build jobs and image tags
    "tests/saimon_mcp/test_search/test_download_fulltext.py",
    "tests/saimon_mcp/test_search/test_download_fulltext_dedup.py",
    "tests/saimon_mcp/test_search/test_download_fulltext_quality.py",
    "tests/saimon_mcp/test_search/test_list_sources_dedupe.py",
    "tests/saimon_mcp/test_search/test_purge_low_quality_fulltext.py",
    "tests/saimon_mcp/test_search/test_academic_torrents_removed.py",
    # tests whose subject is a module this artifact does not ship: leaving them in
    # breaks collection for the whole suite, which hides the tests that do run
    "tests/saimon_mcp/test_content_profiles.py",
    "tests/saimon_mcp/test_generate/test_grounding_binding.py",
    "tests/saimon_mcp/test_integration/test_explore_integration.py",
    "tests/saimon_mcp/test_integration/test_generate_integration.py",
    "tests/saimon_mcp/test_integration/test_evaluate_integration.py",
    "tests/saimon_mcp/test_integration/test_self_extend_integration.py",
    "tests/saimon_mcp/test_integration/test_domain_tools_integration.py",
}

# Anything whose *name* contains one of these is withheld anywhere it appears.
# `seed_data` is deliberately absent: it holds the platform's content-type
# registry and mirrors schema.sql, which services import. What is withheld by
# name is the operator's own seeding and personal configuration.
EXCLUDE_NAME_PARTS = ("shadow", "_seed_", "seed_", "job_hunt")

#: Withheld by name above, but shipped anyway, with the reason.
SHIP_DESPITE_NAME = {"research_shared/seed_data.py": "the content-type registry services import"}

# ---------------------------------------------------------------------------
# Generated in the public tree. Never copied: these differ by design.
# ---------------------------------------------------------------------------

PUBLIC_SOURCES = '''"""sources.py — the composition point: which source adapters this deployment searches.

Every decision about *which* sources exist lives here and nowhere else. Services
ask the registry for adapters; they never name one, so changing the source set is
a change to this file rather than a change scattered across the services.

The adapters registered here are sources any adopter can lawfully reach: a
scholarly index, an open-access resolver, a public digital library, and the
offline stub that needs nothing at all. A source behind a paywall or an
access-controlled library is *your* entitlement, not something this project
distributes: implement it against the adapter contract in
:mod:`research_shared.adapters.base`, register it here in your own tree, and keep
it out of anything you publish.
"""

from __future__ import annotations

from research_shared.adapters.internet_archive import InternetArchiveAdapter
from research_shared.adapters.openalex import OpenAlexAdapter
from research_shared.adapters.ranking import RankingPolicy
from research_shared.adapters.stub import StubAdapter
from research_shared.adapters.unpaywall import UnpaywallAdapter

#: Sources a query searches when it does not name any.
#:
#: Unpaywall is deliberately absent: its search endpoint was retired on
#: 18 September 2026 (it answers 410 Gone), and its own documentation points
#: callers at OpenAlex, which carries the same open-access data. The adapter
#: remains registered as a DOI resolver. The stub is registered but not searched
#: by default: it is for proving an installation, not for research.
DEFAULT_SOURCE_INDEXES = frozenset({"openalex", "internet_archive"})

#: Which sources this deployment trusts most when ranking aggregated results.
RANKING_POLICY = RankingPolicy(
    preferred_sources=frozenset({"openalex"}),
    deprioritised_sources=frozenset({"stub"}),
)

#: Environment variables checked, first one set wins, to decide whether source
#: retrieval happens at all.
SOURCES_ENABLED_ENV_VARS = ("RESEARCH_SOURCES_ENABLED",)

#: Sources full text may be fetched from unless FULLTEXT_DOWNLOAD_CONSENT narrows
#: it. Open access and public archive only.
FULLTEXT_CONSENT_DEFAULT = frozenset({"openalex", "unpaywall", "internet_archive", "stub"})

#: Source used to resolve a bare DOI. Unpaywall answers exactly this question and
#: needs only the caller's own email address, which is why it is the resolver
#: rather than a search source.
DEFAULT_DOI_SOURCE = "unpaywall"

#: Name of the full-text cache table. Override with SAIMON_FULLTEXT_CACHE_TABLE.
FULLTEXT_CACHE_TABLE_DEFAULT = "source_fulltext_cache"

#: ``evidence_type`` stored for evidence backed by a source index.
EVIDENCE_TYPE_SOURCE_INDEX = "source_index"

#: Which sources count as tier A / B / C when scoring how much weight a piece of
#: evidence deserves. Edit for your sources, or empty the dict and citation
#: counts will decide alone.
SOURCE_TIER_INDEXES = {
    "A": frozenset({"pubmed", "crossref", "openalex", "unpaywall"}),
    "B": frozenset({"semantic_scholar", "internet_archive", "dblp"}),
    "C": frozenset({"arxiv", "ssrn", "preprint", "stub"}),
}

#: Retired names still accepted, for callers that predate a rename. Empty in a
#: fresh deployment; see docs/adapters.md for how a deployment adds its own.
PARAM_ALIASES: dict[str, tuple[str, ...]] = {}
METHOD_ALIASES: dict[str, str] = {}
LEGACY_TOOL_ALIASES: dict[str, tuple[str, ...]] = {}


def compose_registry(registry) -> None:
    """Register this deployment's adapters into *registry*."""
    registry.register_all(
        [
            OpenAlexAdapter(),
            UnpaywallAdapter(),
            InternetArchiveAdapter(),
            StubAdapter(),
        ]
    )


def default_source_indexes() -> frozenset[str]:
    """Sources searched when the caller names none."""
    return DEFAULT_SOURCE_INDEXES


def ranking_policy() -> RankingPolicy:
    """How this deployment weights sources when ranking results."""
    return RANKING_POLICY


def fulltext_consent_default() -> frozenset[str]:
    """Sources this deployment consents to fetch full text from."""
    return FULLTEXT_CONSENT_DEFAULT


def default_doi_source() -> str:
    """Source used to resolve a bare DOI."""
    return DEFAULT_DOI_SOURCE


def source_tier_indexes() -> dict[str, frozenset[str]]:
    """This deployment's tier classification of sources."""
    return SOURCE_TIER_INDEXES


def sources_enabled_env_vars() -> tuple[str, ...]:
    """Environment variables that switch source retrieval on or off."""
    return SOURCES_ENABLED_ENV_VARS


def fulltext_cache_table() -> str:
    """Name of the full-text cache table for this deployment."""
    import os

    return os.environ.get("SAIMON_FULLTEXT_CACHE_TABLE", FULLTEXT_CACHE_TABLE_DEFAULT)


def param_aliases() -> dict[str, tuple[str, ...]]:
    """Retired request parameter names this deployment still accepts."""
    return PARAM_ALIASES


def method_aliases() -> dict[str, str]:
    """Retired verification method ids this deployment still serves."""
    return METHOD_ALIASES


def legacy_tool_aliases() -> dict[str, tuple[str, ...]]:
    """Retired tool names this deployment still answers to."""
    return LEGACY_TOOL_ALIASES


def evidence_type_source_index() -> str:
    """``evidence_type`` stored for source-index evidence."""
    return EVIDENCE_TYPE_SOURCE_INDEX
'''


def public_schema_sql() -> str:
    """The public schema: same DDL, generic names, lawful seed rows.

    Transformed rather than hand-written so the two trees stay structurally
    identical: the renames come from REWRITES, and only the seeded source rows
    are replaced -- with sources an adopter can lawfully reach.
    """
    text = apply_rewrites((REPO_ROOT / "schema.sql").read_text(encoding="utf-8"))
    lawful_rows = (
        "    ('source_index',  'openalex',         'OpenAlex',         'A', 'Open scholarly index of works, authors and institutions'),\n"
        "    ('source_index',  'unpaywall',        'Unpaywall',        'A', 'Locates lawful open-access copies of paywalled articles'),\n"
        "    ('source_index',  'internet_archive', 'Internet Archive', 'A', 'Public digital library of books, papers and media'),\n"
        "    ('source_index',  'stub',             'Stub (offline)',   'C', 'Deterministic synthetic source: proves an installation works')\n"
    )
    # Two strings the generic rewrites cannot decide on their own: a comment
    # whose examples name sources, and a tool description inside a JSON literal.
    # The gate scans generated files too, which is how these were found.
    text = text.replace(
        "-- e.g. 'annas_archive', 'libgen', 'scihub'", "-- e.g. 'openalex', 'unpaywall'"
    )
    text = text.replace(
        "Shadow library source indexes to search.", "Source indexes to search."
    )
    start = text.index("    ('source_index',")
    end = text.index(";", start)
    return text[:start] + lawful_rows + text[end:]


def public_compose() -> str:
    """The public compose file: this deployment\'s images parameterised, private
    environment references removed, everything else byte-identical.

    Transformed rather than hand-written so services, ports and dependencies
    cannot drift between the two trees.
    """
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    text = re.sub(
        r"image: ghcr\.io/sv-copilot/saimon:[a-z0-9._-]+",
        "image: ${SAIMON_IMAGE:-saimon:local}",
        text,
    )
    text = re.sub(
        r"^\s*PLANNING_CHECKOUT_PATH:.*$\n",
        "",
        text,
        flags=re.MULTILINE,
    )
    return text


PUBLIC_LICENSE = """\
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

   The full license text is the standard Apache License 2.0; it is reproduced in
   full in the repository's LICENSE file at the published tag.
"""

PUBLIC_ADAPTER_REGISTRY = '''\
"""adapters -- source index adapters.

Each adapter implements the SourceIndexAdapter protocol in `base.py` and connects
to one source of research material. The protocol is the contract: an adapter
declares how it authenticates, what it can search, and what it returns.

The adapters shipped here are sources any adopter can lawfully reach. A source
behind a paywall or an access-controlled library is **the adopter's own
entitlement**, not something this project distributes or helps bypass -- implement
it against this protocol in your own tree, with your own credentials, and keep it
out of anything you publish.

To write your own adapter:

    from research_shared.adapters.base import SourceIndexAdapter, SourceSearchResult

    class MySource(SourceIndexAdapter):
        name = "my-source"
        async def search(self, query: str, limit: int = 20) -> list[SourceSearchResult]:
            ...

See docs/adapters.md for the full contract, including the `access` field an
adapter must declare so callers can tell whether it needs credentials.
"""
'''

PUBLIC_ENV_EXAMPLE = """\
# Saimon Platform -- environment template.
# Copy to .env and fill in real values. Never commit .env.
#
# The names here are the ones the code reads. A variable set under a different
# name will be ignored, however sensible it looks.

# --- Database -------------------------------------------------------------
POSTGRES_PASSWORD=change-me-before-you-run-this
DATABASE_URL=postgresql://saimon:change-me-before-you-run-this@postgres:5432/saimon
SAIMON_ENV=local

# --- Model provider -------------------------------------------------------
# Any OpenAI-compatible endpoint. The adapter is a client, not a dependency.
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# --- Service authentication ----------------------------------------------
# Each service authenticates its callers with its own key. Set what you run;
# a service with no key configured refuses to start rather than running open.
SAIMON_SEARCH_API_KEY=
SAIMON_GENERATE_API_KEY=
SAIMON_EXPORT_API_KEY=
SAIMON_EVALUATE_API_KEY=
SAIMON_VERIFY_API_KEY=
SAIMON_EXPLORE_API_KEY=
SAIMON_DOMAIN_API_KEY=

# --- Optional -------------------------------------------------------------
# Plugin directories the domain service loads at startup.
SAIMON_DOMAIN_PLUGIN_PATHS=plugins
# Secret used to sign caller tokens; generate one per deployment.
SAIMON_JWT_SECRET=change-me-too
# Identity for sources that require one (Unpaywall, polite OpenAlex mailto).
SAIMON_CONTACT_EMAIL=
# Set to false to run with source retrieval off entirely.
RESEARCH_SOURCES_ENABLED=true
# Only needed when migrating from an earlier full-text cache table name.
# SAIMON_FULLTEXT_CACHE_TABLE=source_fulltext_cache
"""

# Files that must exist in the public tree but are not written yet. AGENTS.md is
# deliberately absent: it is a protected agent-instruction file, so it is not
# generated without the operator asking for it. The exporter
# refuses to produce a tree while any of these is pending: a release with a
# placeholder README is worse than no release.
PUBLIC_CI = """name: ci

# The gate runs on every push and pull request, and every check inside it is
# blocking: scripts/preflight.sh exits non-zero when a check fails *or* when a
# check could not run at all.
#
# Generated by the private export tooling, so it cannot drift from the gate it
# invokes.

on:
  push:
    branches: [main]
  pull_request:

jobs:
  preflight:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: install
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install ruff pip-audit

      - name: preflight
        run: bash scripts/preflight.sh
"""


def public_openapi() -> str:
    """A public copy of the aggregated API spec.

    The spec is a checked-in artifact in both trees, so it is transformed rather
    than withheld: the private repository URL and the production host become
    placeholders an adopter edits. The marker gate then scans the result, so a
    private URL surviving this transform fails the export.
    """
    text = (REPO_ROOT / "openapi.json").read_text(encoding="utf-8")
    for private, placeholder in (
        # locations
        ("https://github.com/sv-copilot/saimon", "https://github.com/your-org/saimon"),
        ("http://github.com/sv-copilot/saimon", "https://github.com/your-org/saimon"),
        ("https://mcp.spencervaradi.com", "http://localhost:8000"),
        ("https://mcp-staging.spencervaradi.com", "http://localhost:8001"),
        # the retired tool name and the descriptions that name sources. The
        # spec is a checked-in artifact, so it can lag the code; these keep the
        # public copy describing the public API rather than the retired one.
        ("search_shadow_libraries", "search_sources"),
        (
            "Search shadow library sources (Anna's Archive, LibGen, Sci-Hub, etc.) for academic papers",
            "Search the registered source indexes for academic papers, books and datasets",
        ),
        (
            "List all available source indexes including knowledge graph and shadow library sources",
            "List available source indexes: knowledge graph, registered source indexes, web",
        ),
    ):
        text = text.replace(private, placeholder)
    return text


#: Where the prose that ships as this artifact's documentation is kept, so it is
#: edited as prose and versioned with the record of the export rather than inside
#: a Python string. Override with SAIMON_EXPORT_DOCS.
EXPORT_DOCS = Path(
    os.environ.get("SAIMON_EXPORT_DOCS", "/home/hermes/drake-governance/.docs/public-artifact")
)


def public_doc(name: str):
    """Read a public artifact document, kept as prose in the export record."""

    def _read() -> str:
        return (EXPORT_DOCS / name).read_text(encoding="utf-8")

    return _read


PENDING_GENERATED = {
}

GENERATED = {
    "LICENSE": lambda: PUBLIC_LICENSE,
    "research_shared/sources.py": lambda: PUBLIC_SOURCES,
    "schema.sql": public_schema_sql,
    "docker-compose.yml": public_compose,
    ".github/workflows/ci.yml": lambda: PUBLIC_CI,
    "openapi.json": public_openapi,
    "README.md": public_doc("README.md"),
    "docs/adapters.md": public_doc("docs-adapters.md"),
    "research_shared/adapters/__init__.py": lambda: PUBLIC_ADAPTER_REGISTRY,
    ".env.example": lambda: PUBLIC_ENV_EXAMPLE,
}

# ---------------------------------------------------------------------------
# The scrub gate: markers that must never appear in shipped text.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Rewrites: deterministic renames applied to every shipped text file. The gate
# scans the *rewritten* text, so an incomplete rewrite still fails.
# ---------------------------------------------------------------------------

REWRITES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bshadow_sources_cache\b"), "source_fulltext_cache"),
    (re.compile(r"\bidx_shadow_cache_"), "idx_source_cache_"),
    (re.compile(r"\bshadow_library\b"), "source_index"),
    (re.compile(r"\bshadow libraries\b"), "source indexes"),
    (re.compile(r"\bshadow library\b"), "source index"),
    (re.compile(r"\bshadow sources\b"), "source indexes"),
    (re.compile(r"\bshadow source\b"), "source index"),
    # Capitalised forms appear in prose inside definitions (a content-type
    # parameter description, for instance), where the lowercase patterns above
    # do not reach. The last one is a whole phrase so the result reads correctly
    # rather than "source index source indexes".
    (re.compile(r"\bShadow sources\b"), "Source indexes"),
    (re.compile(r"\bShadow libraries\b"), "Source indexes"),
    (re.compile(r"\bShadow library source indexes\b"), "Registered source indexes"),
    (re.compile(r"\bShadow library\b"), "Source index"),
    # a deployment's own gateway becomes the local default an adopter expects
    (re.compile(r"https://mcp-staging\.spencervaradi\.com/saimon"), "http://localhost:8000"),
    (re.compile(r"https://mcp\.spencervaradi\.com/saimon"), "http://localhost:8000"),
]


def apply_rewrites(text: str) -> str:
    """Apply the deterministic renames to *text*."""
    for pattern, replacement in REWRITES:
        text = pattern.sub(replacement, text)
    return text


#: Files that must contain the markers they look for. Excluded from their own
#: scan; nothing else is. Documented tradeoff: the alternative is a checker that
#: cannot name what it checks for.
SCRUB_TOOL_PATHS = {"scripts/validate_public_tree.py"}

FORBIDDEN = [
    # shadow libraries, by name, host and module
    ("shadow source", re.compile(r"\b(?:libgen|sci[-_]?hub|z-?lib(?:rary)?|annas?[-_ ]?archive|academic[ _-]?torrents)\b", re.IGNORECASE)),
    ("shadow source host", re.compile(r"\b(?:libgen\.[a-z]{2,}|sci-hub\.[a-z]{2,}|annas-archive\.[a-z]{2,})\b", re.IGNORECASE)),
    ("shadow phrasing", re.compile(r"shadow\s+(?:librar|index|registr)", re.IGNORECASE)),
    # the operator's identity, hosts and infrastructure
    ("operator domain", re.compile(r"spencervaradi", re.IGNORECASE)),
    ("operator path", re.compile(r"/Users/simon|/home/simon\b")),
    ("operator infra", re.compile(r"95\.216\.208\.183|nbg1\.your-objectstorage|mcp-staging\.|mcp\.spencervaradi")),
    ("private repo", re.compile(r"sv-copilot/(?:saimon|drake-governance|jobhunter|one-star)|drake-governance")),
    # credential shapes
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("api key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # a real database password in a template
    ("hardcoded db password", re.compile(r"postgres(?:ql)?://[^:\s]+:(?!change-me|\*\*\*|\$\{|%s)[^@\s]{8,}@")),
]


@dataclass(frozen=True)
class PlannedPath:
    destination: str                 # path relative to the public root
    source: Path | None              # None when generated
    generated: str | None = None     # file content when generated


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _excluded(rel: str) -> str | None:
    """Return the reason a path is withheld, or None if it ships."""
    if rel in EXCLUDE_REL_PATHS:
        return "explicitly withheld"
    if rel in SHIP_DESPITE_NAME:
        return None
    if re.search(r"\bshadow\b", rel, re.IGNORECASE):
        return "shadow-library module"
    for part in EXCLUDE_NAME_PARTS:
        if part in Path(rel).name and part not in ("seed_data.py",):
            if rel not in INCLUDE_FILES:
                return f"name matches {part!r}"
    if rel.startswith("tests/") and any(a in rel for a in SHADOW_ADAPTERS):
        return "test for a withheld adapter"
    if rel.startswith("tests/") and "legal_adapters" in rel:
        return "test for a withheld adapter"
    if rel.endswith((".mp3", ".wav", ".m4a", ".pdf", ".epub", ".zip", ".tar", ".gz")):
        return "binary/archive, not reviewed"
    if rel.startswith(".") and rel not in {"", ".gitignore"}:
        return "hidden path"
    return None


def plan_export() -> tuple[list[PlannedPath], list[tuple[str, str]]]:
    plan: list[PlannedPath] = []
    withheld: list[tuple[str, str]] = []

    for rel in INCLUDE_FILES + INCLUDE_SCRIPTS:
        src = REPO_ROOT / rel
        if not src.is_file():
            # Silently skipping an allowlisted path is how the proxy never
            # shipped while the plan looked correct. Say so and stop.
            raise FileNotFoundError(
                f"allowlisted path is not a file: {rel} "
                f"(a directory allowlisted as a file means nothing from it ships)"
            )
        reason = _excluded(rel)
        (withheld.append((rel, reason)) if reason else plan.append(PlannedPath(rel, src)))

    for top in INCLUDE_DIRS:
        root = REPO_ROOT / top
        if not root.is_dir():
            continue
        for src in sorted(root.rglob("*")):
            if not src.is_file() or "__pycache__" in src.parts:
                continue
            rel = _rel(src)
            reason = _excluded(rel)
            (withheld.append((rel, reason)) if reason else plan.append(PlannedPath(rel, src)))

    # A generated path replaces its private twin. Record the replacement rather
    # than dropping it silently, so the report shows the file was superseded --
    # not forgotten. (Dropping it silently was this script's own first bug.)
    generated_dests = set(GENERATED)
    replaced = [p.destination for p in plan if p.destination in generated_dests]
    plan = [p for p in plan if p.destination not in generated_dests]
    withheld.extend((dest, "replaced by the generated public version") for dest in replaced)

    for rel, make in GENERATED.items():
        plan.append(PlannedPath(rel, None, make()))

    withheld.sort()
    return plan, withheld


def scan(plan: list[PlannedPath]) -> list[tuple[str, int, str, str]]:
    """Scan every shipped text file for forbidden markers.

    Returns (destination, line number, marker label, the line) per hit.
    """
    violations = []
    for item in plan:
        if item.destination in SCRUB_TOOL_PATHS:
            continue
        if item.generated is not None:
            text, origin = item.generated, f"{item.destination} (generated)"
        elif item.source and item.source.suffix.lower() in TEXT_SUFFIXES:
            try:
                text, origin = item.source.read_text(encoding="utf-8"), item.destination
            except UnicodeDecodeError:
                continue
        else:
            continue
        text = apply_rewrites(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in FORBIDDEN:
                if pattern.search(line):
                    violations.append((origin, lineno, label, line.strip()[:120]))
    return violations


def syntax_check(plan: list[PlannedPath]) -> list[tuple[str, str]]:
    """Compile every Python file that would ship, and report what will not parse.

    The marker gate proves the absence of private data. It says nothing about
    whether the artifact *works*, and a generated file is exactly where a
    delimiter mistake hides: the gate scans it happily while Python cannot import
    it. Found by running the generated tree, not by reading it.
    """
    failures: list[tuple[str, str]] = []
    for item in plan:
        if not item.destination.endswith(".py"):
            continue
        try:
            if item.generated is not None:
                compile(item.generated, item.destination, "exec")
            elif item.source is not None:
                compile(item.source.read_text(encoding="utf-8"), item.destination, "exec")
        except SyntaxError as exc:
            failures.append((item.destination, f"line {exc.lineno}: {exc.msg}"))
        except UnicodeDecodeError:
            continue
    return failures


def explain(needle: str) -> int:
    plan, withheld = plan_export()
    shipped = [p.destination for p in plan if needle in p.destination]
    held = [(rel, why) for rel, why in withheld if needle in rel]
    print(f"paths matching {needle!r}:\n")
    for dest in shipped:
        print(f"  SHIPS    {dest}")
    for rel, why in held:
        print(f"  WITHHELD {rel}  ({why})")
    if not shipped and not held:
        print("  nothing matches")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", type=Path, help="write the public tree here")
    ap.add_argument("--explain", metavar="SUBSTRING", help="why is this path (not) shipping?")
    ap.add_argument("--allow-pending", action="store_true",
                    help="write even though required generated files are missing (for review only)")
    args = ap.parse_args(argv)

    if args.explain:
        return explain(args.explain)

    try:
        plan, withheld = plan_export()
    except FileNotFoundError as exc:
        print(f"cannot plan: a required export document is missing: {exc.filename}")
        print(f"  looked in {EXPORT_DOCS}")
        print("  these documents live in the planning repository so they are edited as prose")
        return 2
    violations = scan(plan)

    shipped_by_dir: dict[str, int] = {}
    for item in plan:
        top = item.destination.split("/")[0]
        shipped_by_dir[top] = shipped_by_dir.get(top, 0) + 1

    print(f"planned: {len(plan)} paths  |  withheld: {len(withheld)}")
    print("\nshipping by area:")
    for top, n in sorted(shipped_by_dir.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {top}")

    held_by_reason: dict[str, int] = {}
    for _, why in withheld:
        held_by_reason[why] = held_by_reason.get(why, 0) + 1
    print("\nwithheld by reason:")
    for why, n in sorted(held_by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {why}")

    pending = [f"{rel} -- {why}" for rel, why in PENDING_GENERATED.items() if rel not in GENERATED]
    if pending:
        print("\nrequired in the public tree, not written yet:")
        for line in pending:
            print(f"  - {line}")

    syntax_failures = syntax_check(plan)
    if syntax_failures:
        print(f"\nPYTHON THAT WOULD NOT IMPORT -- {len(syntax_failures)} file(s):")
        for dest, why in syntax_failures:
            print(f"  {dest}: {why}")
    else:
        print("\nsyntax: every planned Python file compiles.")

    if violations:
        print(f"\nSCRUB GATE FAILED -- {len(violations)} forbidden marker(s) in files planned for export:")
        by_file: dict[str, list] = {}
        for origin, lineno, label, line in violations:
            by_file.setdefault(origin, []).append((lineno, label, line))
        for origin in sorted(by_file):
            print(f"\n  {origin}")
            for lineno, label, line in by_file[origin][:4]:
                print(f"    line {lineno}  [{label}]  {line}")
            if len(by_file[origin]) > 4:
                print(f"    ... and {len(by_file[origin]) - 4} more")
        print(f"\n{len(by_file)} file(s) must be fixed, rewritten or withheld before anything ships.")
    else:
        print("\nscrub gate: clean -- no forbidden marker in any planned file.")

    if args.output:
        if pending and not args.allow_pending:
            print("\nrefusing to write: required generated files are still pending (see above).")
            return 2
        if violations:
            print("\nrefusing to write: the scrub gate failed.")
            return 3
        if syntax_failures:
            print("\nrefusing to write: the tree would contain Python that cannot import.")
            return 4
        for item in plan:
            dest = args.output / item.destination
            dest.parent.mkdir(parents=True, exist_ok=True)
            if item.destination in SCRUB_TOOL_PATHS:
                # Copied verbatim: rewriting the checker rewrites its marker
                # table, turning a detector of retired names into a detector of
                # the current ones. Caught by running the generated tree.
                shutil.copy2(item.source, dest)
            elif item.generated is not None:
                dest.write_text(apply_rewrites(item.generated), encoding="utf-8")
            elif item.source.suffix.lower() in TEXT_SUFFIXES:
                # The rewrites are applied when writing, exactly as they are when
                # scanning. Applying them only to the scan is how a gate reports
                # clean while the artifact it wrote still carries the markers.
                dest.write_text(
                    apply_rewrites(item.source.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )
            else:
                shutil.copy2(item.source, dest)
            # A shipped script with a shebang has to be runnable: an adopter
            # running ./scripts/preflight.sh must not meet "permission denied".
            if dest.read_text(encoding="utf-8", errors="ignore").startswith("#!"):
                dest.chmod(0o755)
        print(f"\nwrote {len(plan)} paths to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
