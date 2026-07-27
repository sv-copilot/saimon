# AGENTS.md

Operating contract for AI agents working in a **Drake** governance repository.

Drake provides repository-native governance for AI-assisted development: slice
planning, dependency graphs, adapter contracts, and validation tooling.

## Project Context

Saimon is a self-extending platform of 6 atomic MCP services that share one
PostgreSQL knowledge graph. Domain tools (job hunt, writing, research) add
capabilities by registering content types and voice profiles — not by building
new MCPs.

## Branch Policy

- `main` — stable integration branch for adopters.
- `ai-dev` — agent integration branch when using Drake automations.
- `slice/*` — feature branches for isolated slices.

## Validation before PR

From repo root:

```bash
python3 -m pytest tests/ -q
python3 -m compileall research_shared/ mcp/
ruff check research_shared/ mcp/
```

## Scope

- Keep product runtime code in this repository.
- Planning artifacts live in `simon-projects` under `.docs/planning/projects/saimon/`.
- Use `research_shared/` for shared library code (envelope, LLM, DB, auth, resilience, audit).
- Each MCP lives under `mcp/<name>/`.
- Do not commit secrets, API keys, or `.env` files.

## Architecture

- **6 atomic MCPs**: search, generate, export, evaluate, verify, explore
- **Shared PostgreSQL**: all MCPs share one DB; no MCP calls another MCP directly
- **Self-extending**: content types registered at runtime via research-backed flow
- **HTTP/Docker transport**: each MCP runs as a long-running Docker container
- **Fail-closed**: no API key → error. LLM down → degraded response.

## Stack

- Python 3.11+ with FastAPI (HTTP MCP servers)
- PostgreSQL 16 (knowledge graph + extensibility tables)
- Docker (single image, CMD override per MCP)
- DeepSeek (primary LLM) via OpenAI-compatible API

## PR & Merge Workflow

Every slice completes through four gates before merging to `ai-dev`:

### 1. Pre-PR validation (run from repo root)

```bash
python3 -m pytest tests/ -q
python3 -m compileall research_shared/ mcp/
ruff check research_shared/ mcp/
```

All three must pass clean. If `ruff` or `pytest-asyncio` are missing,
install them with `python3 -m pip install ruff pytest-asyncio`.

### 2. Create PR

Push the `slice/*` branch, then create a PR targeting `ai-dev`:

- **Base**: `ai-dev`
- **Compare**: `slice/<name>`
- **Title**: slice name + one-line summary
- **Body**: checklist of what was built, test count, validation results

### 3. Babysit CI

Wait for GitHub Actions (or equivalent) to pass. If something fails:
- Read the failure log
- Fix on the `slice/*` branch
- Push the fix — the PR updates automatically

### 4. Merge

Once CI is green and the PR is approved:
- Merge to `ai-dev` (squash-merge preferred for clean history)
- Delete the `slice/*` branch after merge

### Dependency order for slices

Slices may depend on each other. When starting a new slice that depends
on an unmerged slice, merge the dependency branch into the new branch
first:

```bash
git checkout ai-dev && git pull origin ai-dev
git checkout -b slice/NEXT
git merge slice/PARENT   # bring in unmerged dependency
```

## Slice Inventory

| Slice | Branch | Status | What |
|---|---|---|---|
| SHARED-LIB-1 | `slice/SHARED-LIB-1` | ✅ built (71 tests) | `research_shared/`: envelope, llm, db, auth, resilience, audit |
| MCP-SEARCH-1 | `slice/MCP-SEARCH-1` | ✅ built (15 tests) | `mcp/search/`: FastAPI server, 5 tool endpoints |
| MCP-GENERATE-1 | — | 🔲 next | `mcp/generate/`: LLM content generation MCP |
| MCP-EXPORT-1 | — | 🔲 pending | `mcp/export/`: output formatting MCP |
| MCP-EVALUATE-1 | — | 🔲 pending | `mcp/evaluate/`: quality gate MCP |
| MCP-VERIFY-1 | — | 🔲 pending | `mcp/verify/`: fact-checking MCP |
| MCP-EXPLORE-1 | — | 🔲 pending | `mcp/explore/`: discovery MCP |

## Recursive Prompt for New Sessions

When continuing development in a new session, paste this prompt to
restore full context:

---

```
You are working in the Saimon repository (sv-copilot/saimon).

Read AGENTS.md and .docs/project_intake.json for the full project
contract. Then read the Slice Inventory table in AGENTS.md to see what
has been built and what comes next.

Current state:
- research_shared/ is built (6 modules: envelope, llm, db, auth,
  resilience, audit) with 71 passing tests.
- mcp/search/ is built (FastAPI server, 5 tool endpoints) with 15
  passing tests.
- 5 MCPs remain: generate, export, evaluate, verify, explore.
- All validation gates (pytest + ruff + compileall) are passing.

Follow the PR & Merge Workflow in AGENTS.md: start a new slice branch
from ai-dev, merge any unmerged dependencies via `git merge`, then
follow TDD (RED → GREEN → REFACTOR → PROVE).

Branch: slice/<next-slice-name>
Python: /Users/simon/.pyenv/versions/3.11.8/bin/python

Begin by reading AGENTS.md, then tell me what slice you'll start
and why.
```

- Docker (single image, CMD override per MCP)
- DeepSeek (primary LLM) via OpenAI-compatible API

See `docs/getting-started.md` for a minimal adoption path.
