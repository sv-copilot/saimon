"""Tests for saimon agent-contract docs (SAIMON-AGENTS-AI-DEV-RETIRE-1, #220).

Residual from SAIMON-BRANCH-FLOW-SYNC-1 (#28, PR #142), which only reconciled
``.docs/``. The repo-level agent contracts (``AGENTS.md`` and
``.github/copilot-instructions.md``) still describe the retired ``ai-dev``
branch flow (``slice/* -> ai-dev -> dev``). This is a doc-content regression
gate: any ``ai-dev`` reference in those files fails the suite.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

AGENT_CONTRACT_DOCS = (
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / ".github" / "copilot-instructions.md",
)


def test_agent_contract_docs_exist() -> None:
    for path in AGENT_CONTRACT_DOCS:
        assert path.is_file(), f"missing agent contract doc: {path}"


def test_no_ai_dev_references_in_agent_contract_docs() -> None:
    offenders: list[str] = []
    for path in AGENT_CONTRACT_DOCS:
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if "ai-dev" in line:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                )
    assert not offenders, (
        "stale ai-dev references remain in agent contract docs "
        "(integration branch is dev):\n" + "\n".join(offenders)
    )
