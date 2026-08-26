"""Tests for saimon branch-flow docs (SAIMON-BRANCH-FLOW-SYNC-1, #28).

The registry declares saimon's integration branch as `dev`; the retired
`ai-dev` branch must not linger in the repo's `.docs/`. This is a doc-content
regression gate: any new `ai-dev` reference under `.docs/` fails the suite.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / ".docs"

_DOC_GLOBS = ("*.md", "*.json")


def _doc_files() -> list[Path]:
    files: list[Path] = []
    for glob in _DOC_GLOBS:
        files.extend(DOCS_ROOT.rglob(glob))
    return sorted(files)


def test_no_ai_dev_references_in_docs() -> None:
    offenders: list[str] = []
    for path in _doc_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "ai-dev" in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "stale ai-dev references remain in .docs/ (integration branch is dev):\n"
        + "\n".join(offenders)
    )


def test_project_intake_declares_dev_integration_branch() -> None:
    import json

    intake = json.loads((DOCS_ROOT / "project_intake.json").read_text(encoding="utf-8"))
    assert intake["project"]["integration_branch"] == "dev"
