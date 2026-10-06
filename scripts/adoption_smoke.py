#!/usr/bin/env python3
"""adoption_smoke.py — prove this installation works, with nothing configured.

The first thing a stranger should be able to do after cloning is run this. It
touches no network, needs no key, no database and no container: it asks the
registry for the offline stub source, searches it, deduplicates the results and
ranks them — the same code path a real query takes — then reports what it did.

Exit codes:
    0  the chain ran and produced results
    1  the chain ran and produced nothing (a broken install)
    2  a dependency is missing, so the check could not run at all

That last distinction matters: a check that cannot run is a failure, not a skip.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Running `python scripts/adoption_smoke.py` puts the *script's* directory on
# sys.path, not the repository root, so import the project from where it lives.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fail_missing(module: str, exc: Exception) -> int:
    print(f"cannot run: {module} is not importable ({exc})")
    print("install the project first: pip install -r requirements.txt")
    return 2


async def main() -> int:
    try:
        from research_shared.adapters.dedup import deduplicate
        from research_shared.adapters.ranking import rank_results
        from research_shared.source_registry import (
            adapter_access,
            adapter_kind,
            adapter_label,
            get_registry,
        )
    except ImportError as exc:  # pragma: no cover - depends on the environment
        return _fail_missing(getattr(exc, "name", "a project module"), exc)

    print("1. composing the registry from research_shared.sources")
    registry = get_registry()
    names = registry.list_names()
    print(f"   registered: {', '.join(names) or '(nothing)'}")
    if not names:
        print("   FAIL: this deployment registers no sources at all")
        return 1

    print("2. describing each source")
    for adapter in registry.list_all():
        print(
            f"   {adapter.name:16s} {adapter_label(adapter)[:28]:28s} "
            f"tier={adapter.tier} kind={adapter_kind(adapter):8s} access={adapter_access(adapter)}"
        )

    print("3. searching the offline stub (no network, no key)")
    stub = registry.get("stub")
    if stub is None:
        print("   note: this deployment registers no stub adapter; using the first registered source")
        stub = registry.list_all()[0]
    hits = await stub.search("verifiable cumulative research", limit=3)
    print(f"   {len(hits)} result(s) from {stub.name}")

    print("4. deduplicating and ranking")
    ranked = rank_results(deduplicate(hits))
    for result in ranked:
        label = result.doi or result.identifier
        print(f"   - {label:34s} {(result.title or '')[:44]}")

    if not ranked:
        print("\nFAIL: the chain ran but produced no results")
        return 1

    print(f"\nOK: {len(ranked)} result(s) through the full chain, offline.")
    print("next: read docs/adapters.md to register a source of your own,")
    print("      or set RESEARCH_SOURCES_ENABLED and configure the sources you have access to.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
