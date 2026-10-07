#!/usr/bin/env python3
"""validate_public_tree.py — this tree contains nothing it should not.

A public artifact is not clean because it was cleaned once; it is clean because
something keeps checking. This runs in CI on every push and in `preflight.sh`, so
a marker reintroduced by a future commit fails the build instead of going live.

It checks two things:

1. **No forbidden markers** in any tracked text file: private source names,
   the operator's domains, hosts and paths, private repo references, credential
   shapes, and the retired table name.
2. **The areas that make this an artifact rather than a snapshot still exist** —
   the layout an adopter's instructions depend on.

This file contains the markers it searches for, which is why it excludes itself.
That is a deliberate tradeoff: the alternative is a scanner that cannot name what
it is scanning for.

Exit: 0 clean · 1 findings.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF = "scripts/validate_public_tree.py"

#: Directories that are never part of the shipped source.
SKIP_DIRS = {".venv", "venv", ".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache"}

TEXT_SUFFIXES = {
    ".md", ".py", ".sh", ".json", ".yml", ".yaml", ".toml", ".sql", ".txt",
    ".cfg", ".ini", ".example", ".in", ".js", ".ts", ".tsx",
}

FORBIDDEN: list[tuple[str, re.Pattern[str]]] = [
    ("private source", re.compile(r"\b(?:libgen|sci[-_]?hub|z-?lib(?:rary)?|annas?[-_ ]?archive|academic[ _-]?torrents)\b", re.IGNORECASE)),
    ("private source host", re.compile(r"\b(?:libgen\.[a-z]{2,}|sci-hub\.[a-z]{2,}|annas-archive\.[a-z]{2,})\b", re.IGNORECASE)),
    ("private phrasing", re.compile(r"shadow\s+(?:librar|index|registr|source)", re.IGNORECASE)),
    ("operator domain", re.compile(r"spencervaradi", re.IGNORECASE)),
    ("operator path", re.compile(r"/Users/simon|/home/simon\b")),
    ("operator infra", re.compile(r"95\.216\.208\.183|nbg1\.your-objectstorage|mcp-staging\.|mcp\.spencervaradi")),
    ("private repo", re.compile(r"sv-copilot/(?:saimon|drake-governance|jobhunter|one-star)|drake-governance")),
    ("retired table name", re.compile(r"shadow_sources_cache")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("api key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

#: Paths whose absence would mean this is no longer the artifact the instructions
#: describe. A wholesale overwrite is the failure this guards against.
REQUIRED_PATHS = [
    "research_shared/source_registry.py",   # the registry services depend on
    "research_shared/sources.py",           # the composition point
    "research_shared/adapters/base.py",     # the contract
    "research_shared/adapters/stub.py",     # the offline path
    "saimon_mcp/search",                    # a service, not just a library
    "saimon_mcp/verify",
    "scripts/preflight.sh",                 # the gate
    "scripts/adoption_smoke.py",            # the first thing an adopter runs
    "scripts/validate_public_tree.py",      # this checker
    "docs/adapters.md",                     # how to add a source
    "tests",                                # a test suite the adopter can run
    ".github/workflows/ci.yml",             # the gate runs somewhere
]


def tracked_text_files() -> list[Path]:
    """Every tracked text file, via git: what an adopter actually receives."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        # No git (e.g. an unpacked tarball): fall back to walking the tree.
        out = "\n".join(
            str(p.relative_to(REPO_ROOT))
            for p in REPO_ROOT.rglob("*")
            if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)
        )
    files = []
    for line in out.splitlines():
        rel = line.strip()
        if not rel or rel == SELF:
            continue
        # Never scan a virtualenv, a bytecode cache or a package directory that
        # an adopter installed: those are not this project's files, and a marker
        # inside somebody else's package is not this tree's problem.
        if any(part in SKIP_DIRS for part in Path(rel).parts):
            continue
        path = REPO_ROOT / rel
        if path.suffix.lower() in TEXT_SUFFIXES and path.is_file():
            files.append(path)
    return files


def scan() -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    for path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in FORBIDDEN:
                if pattern.search(line):
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    findings.append((rel, lineno, label, line.strip()[:110]))
    return findings


def missing_paths() -> list[str]:
    return [p for p in REQUIRED_PATHS if not (REPO_ROOT / p).exists()]


def main() -> int:
    print("validate_public_tree: scanning tracked text files")
    files = tracked_text_files()
    print(f"  {len(files)} file(s) scanned")

    findings = scan()
    missing = missing_paths()

    if findings:
        print(f"\nFORBIDDEN MARKERS in {len({f[0] for f in findings})} file(s):")
        for rel, lineno, label, line in findings[:40]:
            print(f"  {rel}:{lineno}  [{label}]  {line}")
        if len(findings) > 40:
            print(f"  ... and {len(findings) - 40} more")

    if missing:
        print("\nMISSING REQUIRED PATHS:")
        for path in missing:
            print(f"  {path}")

    if findings or missing:
        print(f"\nFAILED: {len(findings)} marker(s), {len(missing)} missing path(s)")
        return 1

    print("clean: no forbidden marker, every required path present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
