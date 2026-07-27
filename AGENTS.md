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
| SHARED-LIB-1 | `slice/SHARED-LIB-1` | ✅ merged | `research_shared/`: envelope, llm, db, auth, resilience, audit |
| MCP-SEARCH-1 | `slice/MCP-SEARCH-1` | ✅ merged | `mcp/search/`: FastAPI server, 5 tool endpoints |
| MCP-GENERATE-1 | `slice/MCP-GENERATE-1` | ✅ merged | `mcp/generate/`: LLM content generation MCP |
| MCP-EXPORT-1 | `slice/MCP-EXPORT-1` | ✅ merged | `mcp/export/`: output formatting MCP |
| MCP-EVALUATE-1 | `slice/MCP-EVALUATE-1` | ✅ merged | `mcp/evaluate/`: quality gate MCP |
| MCP-VERIFY-1 | `slice/MCP-VERIFY-1` | ✅ merged | `mcp/verify/`: fact-checking MCP |
| MCP-EXPLORE-1 | `slice/MCP-EXPLORE-1` | ✅ merged | `mcp/explore/`: discovery MCP |
| DOCKER-1 | `slice/DOCKER-1` | ✅ merged | Dockerfile, docker-compose (7 svc + PG16), entrypoint, .dockerignore, schema.sql |
| DOMAIN-BOOTSTRAP-1 | `slice/DOMAIN-BOOTSTRAP-1` | ✅ built | `research_shared/seed_data.py`: 13 content types, 5 voice profiles, 15 seed requests; updated schema.sql |

## Session Startup Protocol

Every new session MUST start by consolidating work from prior sessions
before starting any new slice.  This prevents drift and ensures `ai-dev`
always reflects merged, tested code.

Follow these steps in order.  Stop at any step if you need the operator
to review or approve something (e.g., a PR).

### Step 0 — Pull latest

```bash
git checkout ai-dev && git pull origin ai-dev
```

### Step 1 — Discover unmerged slice branches

List all remote `slice/*` branches that have **not** been merged into
`ai-dev`:

```bash
git branch -r --no-merged origin/ai-dev | grep 'slice/'
```

For each found branch, inspect its state:

```bash
git log origin/<branch> --oneline -5
```

### Step 2 — Create PRs for unmerged branches

For each unmerged `slice/*` branch, use the GitHub CLI or API to check
if a PR already exists:

```bash
gh pr list --base ai-dev --head <branch> --json number,state,title
```

If no PR exists, create one:

```bash
gh pr create \
  --base ai-dev \
  --head <branch> \
  --title "<slice-name>: <one-line summary>" \
  --body "## What was built
- ...
- ...

## Validation
- \`N\` tests pass
- ruff: clean
- compileall: OK"
```

### Step 3 — Babysit open PRs

For each open PR, check CI status:

```bash
gh pr view <PR-number> --json state,statusCheckRollup
```

If CI is failing:
- Checkout the branch: `git checkout <branch>`
- Run validation locally: `python3 -m pytest tests/ -q`
- Fix the issue, commit, push — the PR updates automatically

Do NOT start a new slice until all open PRs are green or the operator
decides to defer one.

### Step 4 — Merge ready PRs

Once CI is green and the operator approves:

```bash
gh pr merge <PR-number> --squash --delete-branch
```

After merge, pull the updated `ai-dev`:

```bash
git checkout ai-dev && git pull origin ai-dev
```

### Step 5 — Update Slice Inventory

After merging, update the Slice Inventory table below:
- Change the merged slice's status from `✅ built` to `✅ merged`
- The table is the source of truth for what's in `ai-dev`

### Step 6 — Start next slice

Only after all mergeable slices are consolidated:

```bash
git checkout -b slice/<NEXT-SLICE>
```

If the next slice depends on unmerged work, merge the dependency:

```bash
git merge slice/<PARENT>   # bring in unmerged dependency
```

Then follow TDD: RED → GREEN → REFACTOR → PROVE.

## Slice Inventory

| Slice | Branch | Status | What |
|---|---|---|---|
| SHARED-LIB-1 | `slice/SHARED-LIB-1` | ✅ merged | `research_shared/`: envelope, llm, db, auth, resilience, audit |
| MCP-SEARCH-1 | `slice/MCP-SEARCH-1` | ✅ merged | `mcp/search/`: FastAPI server, 5 tool endpoints |
| MCP-GENERATE-1 | `slice/MCP-GENERATE-1` | ✅ merged | `mcp/generate/`: LLM content generation MCP |
| MCP-EXPORT-1 | `slice/MCP-EXPORT-1` | ✅ merged | `mcp/export/`: output formatting MCP |
| MCP-EVALUATE-1 | `slice/MCP-EVALUATE-1` | ✅ merged | `mcp/evaluate/`: quality gate MCP |
| MCP-VERIFY-1 | `slice/MCP-VERIFY-1` | ✅ merged | `mcp/verify/`: fact-checking MCP |
| MCP-EXPLORE-1 | `slice/MCP-EXPLORE-1` | ✅ merged | `mcp/explore/`: discovery MCP |
| DOCKER-1 | `slice/DOCKER-1` | ✅ merged | Dockerfile, docker-compose (7 svc + PG16), entrypoint, .dockerignore, schema.sql |
| DOMAIN-BOOTSTRAP-1 | `slice/DOMAIN-BOOTSTRAP-1` | ✅ built | `research_shared/seed_data.py`: 13 content types, 5 voice profiles, 15 seed requests; updated schema.sql |

## Recursive Prompt for New Sessions

When continuing development in a new session, paste this prompt to
restore full context.  The agent will follow the **Session Startup
Protocol** above — consolidating prior work before starting anything
new.

---

```
You are working in the Saimon repository (sv-copilot/saimon).

## 1. Read the contract

Read AGENTS.md (the full file — it contains the Session Startup
Protocol, PR workflow, Slice Inventory, and architecture) and
.docs/project_intake.json.

## 2. Consolidate prior work

Follow the Session Startup Protocol in AGENTS.md:

a. Pull latest ai-dev.
b. Discover unmerged slice/* branches (git branch -r --no-merged).
c. For each: create a PR targeting ai-dev if one doesn't exist.
   Use `gh pr create` with base=ai-dev, head=<branch>.
d. Check CI on each PR. If failing, fix on the branch and push.
e. Merge ready PRs (squash-merge, delete branch).
f. Update the Slice Inventory table after each merge.
g. Pull ai-dev again.

Do NOT start a new slice until all prior slices are merged into
ai-dev or the operator explicitly defers one.

## 3. Start the next slice

Once consolidated, read the Slice Inventory to pick the next slice.
The current next is **MCP-INTEGRATION-1** (wire MCPs to real
backends: DB, LLM, SelfExtender, canonical seed_data). Create a
new branch from ai-dev, then follow TDD:
RED → GREEN → REFACTOR → PROVE.

## 4. Current state (auto-updated)

- 9 of 9 slices merged: shared-lib + 6 MCPs + Docker + self-extend
- DOMAIN-BOOTSTRAP-1 built (PR #9 pending): 13 content types,
  5 voice profiles, 15 seed requests
- 307 tests passing, ruff clean, compileall OK
- research_shared/: envelope, llm, db, auth, resilience, audit,
  self_extend, seed_data (8 modules)
- All 6 MCPs structurally complete but return synthetic/stub
  responses — not yet wired to real backends
- Next: MCP-INTEGRATION-1 — wire to DB, LLM, SelfExtender

## 5. Environment

- Branch: ai-dev
- Python: /Users/simon/.pyenv/versions/3.11.8/bin/python
- Validation: python3 -m pytest tests/ -q
- Lint: ruff check research_shared/ mcp/
- Compile: python3 -m compileall research_shared/ mcp/

Begin by reading AGENTS.md in full, then tell me what you see:
which slices are unmerged, which PRs need attention, and what
you'll build next.
```


```
You are working in the Saimon repository (sv-copilot/saimon).

Read AGENTS.md and .docs/project_intake.json for the full project
contract. Then read the Slice Inventory table in AGENTS.md to see what
has been built and what comes next.

Current state:
- research_shared/ is built (8 modules: envelope, llm, db, auth,
  resilience, audit, self_extend, seed_data).
- 9 of 9 slices merged: all 6 MCPs + shared-lib + Docker/Compose
  + self-extension
- DOMAIN-BOOTSTRAP-1 built (PR #9): 13 content types, 5 voice
  profiles, 15 seed requests; updated schema.sql
- 307 tests passing, ruff clean, compileall OK
- Docker + Compose: built and merged
- All 6 MCPs structurally complete but return synthetic/stub
  responses — not yet wired to real DB, LLM, or SelfExtender

Next phase: MCP-INTEGRATION-1 — wire MCPs to real backends.
See .docs/project_intake.json for success criteria.

Follow the PR & Merge Workflow in AGENTS.md: start a new slice branch
from ai-dev, merge any unmerged dependencies via `git merge`, then
follow TDD (RED → GREEN → REFACTOR → PROVE).

Branch: ai-dev
Python: /Users/simon/.pyenv/versions/3.11.8/bin/python

Begin by reading AGENTS.md, then tell me what you see and what
you'll build next.
```

- Docker (single image, CMD override per MCP)
- DeepSeek (primary LLM) via OpenAI-compatible API

See `docs/getting-started.md` for a minimal adoption path.
