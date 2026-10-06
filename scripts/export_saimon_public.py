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
    "saimon_mcp",          # the nine MCP services: the platform itself
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
    "tools/saimon-mcp-proxy",   # the proxy is the adopter's client entry point
]

# Scripts worth shipping: the ones that operate on a public adopter's own data.
INCLUDE_SCRIPTS = [
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
    "research_shared/adapters/base.py",         # the CONTRACT, but its field descriptions and
                                                # example labels name the sources: rewritten
                                                # deliberately (see PENDING_GENERATED)
    "research_shared/shadow_registry.py",
    "tests/test_shadow_registry.py",
    # operator-only data and operations
    "research_shared/content_ops_seed.py",
    "research_shared/job_hunt_config.py",
    "research_shared/seed_data.py",
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
}

# Anything whose *name* contains one of these is withheld anywhere it appears.
EXCLUDE_NAME_PARTS = ("shadow", "_seed_", "seed_", "job_hunt")

# ---------------------------------------------------------------------------
# Generated in the public tree. Never copied: these differ by design.
# ---------------------------------------------------------------------------

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
'''

PUBLIC_ENV_EXAMPLE = """\
# Saimon Platform -- environment template.
# Copy to .env and fill in real values. Never commit .env.

# --- Database -------------------------------------------------------------
POSTGRES_DB=saimon
POSTGRES_USER=saimon
POSTGRES_PASSWORD=change-me-before-you-run-this
DATABASE_URL=postgresql://saimon:change-me-before-you-run-this@postgres:5432/saimon

# --- Model provider -------------------------------------------------------
# Any OpenAI-compatible endpoint. The adapter is a client, not a dependency.
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=
LLM_MODEL=deepseek-chat
EMBEDDING_MODEL=BAAI/bge-m3

# --- Services -------------------------------------------------------------
# Ports are internal to the compose network; publish only what you need.
SEARCH_MCP_PORT=8001
GENERATE_MCP_PORT=8002
EXPORT_MCP_PORT=8003
EVALUATE_MCP_PORT=8004
VERIFY_MCP_PORT=8005
EXPLORE_MCP_PORT=8006

# --- Optional: sources that need an identity ------------------------------
# Leave blank to run entirely on the bundled stub and public-domain sources.
OPENALEX_EMAIL=
CROSSREF_MAILTO=
"""

# Files that must exist in the public tree but are not written yet. The exporter
# refuses to produce a tree while any of these is pending: a release with a
# placeholder README is worse than no release.
PENDING_GENERATED = {
    "research_shared/adapters/base.py": "the rewritten public contract: generic field descriptions and examples",
    "research_shared/adapters/stub.py": "the stub adapter: the whole path runnable with no network and no key",
    "research_shared/adapters/openalex.py": "lawful source, no credential required",
    "research_shared/adapters/unpaywall.py": "lawful source, needs only an email",
    "README.md": "the public front door (docs workstream)",
    "AGENTS.md": "agent-agnostic working agreement (docs workstream)",
    ".github/workflows/ci.yml": "public CI: the gate, with every check blocking",
    "docs/adapters.md": "the adapter contract, written for an outside implementer",
}

GENERATED = {
    "LICENSE": lambda: PUBLIC_LICENSE,
    "research_shared/adapters/__init__.py": lambda: PUBLIC_ADAPTER_REGISTRY,
    ".env.example": lambda: PUBLIC_ENV_EXAMPLE,
}

# ---------------------------------------------------------------------------
# The scrub gate: markers that must never appear in shipped text.
# ---------------------------------------------------------------------------

FORBIDDEN = [
    # shadow libraries, by name, host and module
    ("shadow source", re.compile(r"\b(?:libgen|sci[-_]?hub|z-?lib(?:rary)?|annas?[-_ ]?archive|academic[ _-]?torrents)\b", re.I)),
    ("shadow source host", re.compile(r"\b(?:libgen\.[a-z]{2,}|sci-hub\.[a-z]{2,}|annas-archive\.[a-z]{2,})\b", re.I)),
    ("shadow phrasing", re.compile(r"shadow\s+(?:librar|index|registr)", re.I)),
    # the operator's identity, hosts and infrastructure
    ("operator domain", re.compile(r"spencervaradi", re.I)),
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
    if re.search(r"\bshadow\b", rel, re.I):
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
            continue
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
        if item.generated is not None:
            text, origin = item.generated, f"{item.destination} (generated)"
        elif item.source and item.source.suffix.lower() in TEXT_SUFFIXES:
            try:
                text, origin = item.source.read_text(encoding="utf-8"), item.destination
            except UnicodeDecodeError:
                continue
        else:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in FORBIDDEN:
                if pattern.search(line):
                    violations.append((origin, lineno, label, line.strip()[:120]))
    return violations


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

    plan, withheld = plan_export()
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
        for item in plan:
            dest = args.output / item.destination
            dest.parent.mkdir(parents=True, exist_ok=True)
            if item.generated is not None:
                dest.write_text(item.generated, encoding="utf-8")
            else:
                shutil.copy2(item.source, dest)
        print(f"\nwrote {len(plan)} paths to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
