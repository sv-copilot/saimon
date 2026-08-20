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

- `main` — stable production branch.  Triggers CI (validate only).
- `dev` — staging branch.  Push triggers CI validate → GHCR push → auto-deploy
  to staging VPS (95.216.208.183).
- `ai-dev` — agent integration branch for Drake-assisted development.  Triggers
  CI (validate + Docker build, no push).
- `slice/*` — feature branches for isolated slices.

### Branch flow

```
slice/* ──PR──▶ ai-dev ──merge──▶ dev ──CI deploy──▶ staging ──PR──▶ main
```

- `ai-dev` → `dev`: merge when ready for staging consumption.
- `dev` → `main`: PR when staging is validated and ready for production.

## Validation before PR

From repo root:

```bash
python3 -m pytest tests/ -q
python3 -m compileall research_shared/ saimon_mcp/
ruff check research_shared/ saimon_mcp/
pip-audit --requirement requirements.txt
```

## Scope

- Keep product runtime code in this repository.
- Planning artifacts live in `simon-projects` under `.docs/planning/projects/saimon/`.
- Use `research_shared/` for shared library code (envelope, LLM, DB, auth, resilience, audit).
- Each MCP lives under `saimon_mcp/<name>/`.
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
python3 -m compileall research_shared/ saimon_mcp/
ruff check research_shared/ saimon_mcp/
pip-audit --requirement requirements.txt
```

All four must pass clean. If `ruff`, `pytest-asyncio`, or `pip-audit`
are missing, install them with
`python3 -m pip install ruff pytest-asyncio pip-audit`.

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

## Slice Lifecycle

All slice planning and state tracking lives in the **canonical planning tree**
at `simon-projects/.docs/planning/projects/saimon/slice_dependency_tree.json`.
This file is the single source of truth for what's planned, in progress, merged,
and promoted.

### The local dev loop

```
PLAN (simon-projects)  →  IMPLEMENT (saimon)  →  SYNC (simon-projects)
```

1. **SHAPE** — Add slice to the planning tree, write detail doc in
   `simon-projects/.docs/planning/projects/saimon/slices/<SLICE-ID>.md`.
2. **PROMOTE** — Move slice to `state: ready` when ready to implement.
3. **IMPLEMENT** — Branch `slice/<SLICE-ID>` from `ai-dev`, build + test,
   open PR to `ai-dev`, merge.
4. **TREE-SYNC** — Update the planning tree: set `state`, `last_known_pr`,
   `branch_posture`. Validate with:
   ```bash
   cd /Users/simon/projects
   python3 scripts/validate_slice_dependency_tree.py \
     --tree .docs/planning/projects/saimon/slice_dependency_tree.json
   ```

**Never maintain a duplicate slice list in this file.** The planning tree
is authoritative. The `## Slice Inventory` section below is a read-only
historical snapshot of slices merged before 2026-07-29.

## Historical Slice Inventory (pre-canonical-tree)

These slices were implemented before the canonical planning tree loop was
enforced. They are listed here for reference only; all future slices are
tracked in
`simon-projects/.docs/planning/projects/saimon/slice_dependency_tree.json`.

| Slice | Branch | Status | What |
|---|---|---|---|
| SHARED-LIB-1 | `slice/SHARED-LIB-1` | ✅ merged | `research_shared/`: envelope, llm, db, auth, resilience, audit |
| MCP-SEARCH-1 | `slice/MCP-SEARCH-1` | ✅ merged | `saimon_mcp/search/`: FastAPI server, 5 tool endpoints |
| MCP-GENERATE-1 | `slice/MCP-GENERATE-1` | ✅ merged | `saimon_mcp/generate/`: LLM content generation MCP |
| MCP-EXPORT-1 | `slice/MCP-EXPORT-1` | ✅ merged | `saimon_mcp/export/`: output formatting MCP |
| MCP-EVALUATE-1 | `slice/MCP-EVALUATE-1` | ✅ merged | `saimon_mcp/evaluate/`: quality gate MCP |
| MCP-VERIFY-1 | `slice/MCP-VERIFY-1` | ✅ merged | `saimon_mcp/verify/`: fact-checking MCP |
| MCP-EXPLORE-1 | `slice/MCP-EXPLORE-1` | ✅ merged | `saimon_mcp/explore/`: discovery MCP |
| DOCKER-1 | `slice/DOCKER-1` | ✅ merged | Dockerfile, docker-compose (7 svc + PG16), entrypoint, .dockerignore, schema.sql |
| DOMAIN-BOOTSTRAP-1 | `slice/DOMAIN-BOOTSTRAP-1` | ✅ merged | `research_shared/seed_data.py`: 13 content types, 5 voice profiles, 15 seed requests; updated schema.sql |
| MCP-INTEGRATION-1 | `slice/MCP-INTEGRATION-1` | ✅ merged | Wire MCPs to real backends: LLM, DB, seed_data; 333 tests + 26 integration tests |
| SELF-EXTEND-2 | `slice/SELF-EXTEND-2` | ✅ merged | `seed_loader.py` + generate-mcp self-extend wiring; 358 tests |
| DEPLOY-HARDEN-1 | `slice/DEPLOY-HARDEN-1` | ✅ merged | Secrets management, graceful shutdown, deep health checks, CI/CD, prod compose; 432 tests |
| LIVE-INTEGRATION-1 | `slice/LIVE-INTEGRATION-1` | ✅ merged | Real LLM (DeepSeek via openai), real DB (asyncpg), live E2E integration tests (17 tests); 432 tests |
| DOMAIN-TOOLS-1 | `slice/DOMAIN-TOOLS-1` | ✅ merged | Job Hunt domain: 5 content types, 3 voice profiles, 10 seed requests, generate_job_hunt_content tool; 488 tests |

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

### Step 5 — Tree-sync the planning tree

After merging, update the Slice Inventory table below:
- Change the merged slice's status from `✅ built` to `✅ merged`
- The table is the source of truth for what's in `ai-dev`

### Step 6 — Start next slice

Only after all mergeable slices are consolidated.

**Finding the next slice:** Check the Slice Inventory table above for the
first slice with status `📋 designed`.  Read its design doc under
`.docs/planning/projects/saimon/<SLICE>-design.md` for the full spec.

If no designed slice exists, check `.docs/project_intake.json` for
upcoming work.

```bash
cd /Users/simon/projects
git pull --rebase origin ai-dev
```

Update `.docs/planning/projects/saimon/slice_dependency_tree.json`:
- Set `state`: `validated` (merged to `ai-dev`), `promoted` (merged to `dev`)
- Set `branch_posture.merged_branch`, `branch_posture.promoted_branch`
- Set `branch_posture.last_known_pr` to the PR number
- Set `status: done`

Validate and commit:
```bash
python3 scripts/validate_slice_dependency_tree.py \
  --tree .docs/planning/projects/saimon/slice_dependency_tree.json
python3 -m json.tool .docs/projects-registry.json >/dev/null
git diff --check
git add .docs/planning/projects/saimon/
git commit -m "tree-sync: saimon — <SLICE-ID> validated (PR #<N> merged to ai-dev)"
git push origin ai-dev
```

See `.github/skills/tree-sync-after-merge/SKILL.md` for the full procedure.

### Step 6 — Start next slice from the planning tree

Only after all mergeable slices are consolidated and tree-synced.

**Finding the next slice:** Check the canonical planning tree — NOT a local
table in this file:

```bash
cd /Users/simon/projects
python3 scripts/select_next_automation_slice.py \
  --tree .docs/planning/projects/saimon/slice_dependency_tree.json
```

If the selector returns a slice, read its detail doc:
```bash
cat .docs/planning/projects/saimon/slices/<SLICE-ID>.md
```

If no slice is ready, check the backlog:
```bash
cat .docs/planning/projects/saimon/slice_backlog.md
```

Then shape the next slice (add to tree + write detail doc) before implementing.

```bash
cd /Users/simon/saimon
git checkout ai-dev && git pull origin ai-dev
git checkout -b slice/<SLICE-ID>
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
| MCP-SEARCH-1 | `slice/MCP-SEARCH-1` | ✅ merged | `saimon_mcp/search/`: FastAPI server, 5 tool endpoints |
| MCP-GENERATE-1 | `slice/MCP-GENERATE-1` | ✅ merged | `saimon_mcp/generate/`: LLM content generation MCP |
| MCP-EXPORT-1 | `slice/MCP-EXPORT-1` | ✅ merged | `saimon_mcp/export/`: output formatting MCP |
| MCP-EVALUATE-1 | `slice/MCP-EVALUATE-1` | ✅ merged | `saimon_mcp/evaluate/`: quality gate MCP |
| MCP-VERIFY-1 | `slice/MCP-VERIFY-1` | ✅ merged | `saimon_mcp/verify/`: fact-checking MCP |
| MCP-EXPLORE-1 | `slice/MCP-EXPLORE-1` | ✅ merged | `saimon_mcp/explore/`: discovery MCP |
| DOCKER-1 | `slice/DOCKER-1` | ✅ merged | Dockerfile, docker-compose (7 svc + PG16), entrypoint, .dockerignore, schema.sql |
| DOMAIN-BOOTSTRAP-1 | `slice/DOMAIN-BOOTSTRAP-1` | ✅ merged | `research_shared/seed_data.py`: 13 content types, 5 voice profiles, 15 seed requests; updated schema.sql |
| MCP-INTEGRATION-1 | `slice/MCP-INTEGRATION-1` | ✅ merged | Wire MCPs to real backends: LLM, DB, seed_data; 333 tests + 26 integration tests |
| SELF-EXTEND-2 | `slice/SELF-EXTEND-2` | ✅ merged | `seed_loader.py` + generate-mcp self-extend wiring; 358 tests |
| DEPLOY-HARDEN-1 | `slice/DEPLOY-HARDEN-1` | ✅ merged | Secrets management, graceful shutdown, deep health checks, CI/CD, prod compose; 432 tests |
| LIVE-INTEGRATION-1 | `slice/LIVE-INTEGRATION-1` | ✅ merged | Real LLM (DeepSeek via openai), real DB (asyncpg), live E2E integration tests (17 tests); 432 tests |
| DOMAIN-TOOLS-1 | `slice/DOMAIN-TOOLS-1` | ✅ merged | Job Hunt domain: 5 content types, 3 voice profiles, 10 seed requests, generate_job_hunt_content tool; 488 tests |
| SHADOW-SEARCH-1 | `slice/SHADOW-SEARCH-1` | ✅ built | Shadow library source integration: search tool, verify pipeline, 5 adapters, terminology fix; 616 tests |

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
Protocol, PR workflow, canonical planning tree reference, and
architecture) and .docs/project_intake.json.

## 2. Consolidate prior work

Follow the Session Startup Protocol in AGENTS.md:

a. Pull latest ai-dev.
b. Discover unmerged slice/* branches (git branch -r --no-merged).
c. For each: create a PR targeting ai-dev if one doesn't exist.
   Use `gh pr create` with base=ai-dev, head=<branch>.
d. Check CI on each PR. If failing, fix on the branch and push.
e. Merge ready PRs (squash-merge, delete branch).
f. Tree-sync the planning tree in simon-projects after each merge
   (see Step 5 above).
g. Pull ai-dev again.

Do NOT start a new slice until all prior slices are merged into
ai-dev or the operator explicitly defers one.

## 3. Start the next slice

Once consolidated, check the Slice Inventory for the first slice with
status `📋 designed`.  Read its design doc under
`.docs/planning/projects/saimon/<SLICE>-design.md` for the full spec
and TDD outline.  Create a new branch from ai-dev, then follow TDD:
RED → GREEN → REFACTOR → PROVE.

## 4. Current state (auto-updated)

- 16 of 16 slices merged (all mergeable) + SHADOW-SEARCH-1 built (ready for PR)
- All 6 MCPs wired to LLM/DB backends with dependency injection
- 616 tests passing, ruff clean, compileall OK
- Terminology fix applied: list_sources → list_source_indexes
- Shadow library integration: search_shadow_libraries tool, 5 adapters, dedup engine, shadow_registry
- research_shared/: envelope, llm, db, auth, resilience, audit, self_extend, seed_data, seed_loader, shadow_registry, adapters/ (14 modules)
- Content types sourced from seed_data.py (14 types including bibliography, 5 voice profiles)
- Runtime self-extension: unknown types trigger research → auto-register via SelfExtender
- DB re-seed resilience: SeedLoader loads canonical data on demand
- All 4 success criteria from project_intake.json met
- Next: TBD — check .docs/project_intake.json

## 5. Environment

- Branch: ai-dev
- Python: python3.11 (via pyenv or system)
- Validation: python3 -m pytest tests/ -q
- Lint: ruff check research_shared/ saimon_mcp/
- Compile: python3 -m compileall research_shared/ saimon_mcp/

Begin by reading AGENTS.md in full, then tell me what you see:
which slices are unmerged, which PRs need attention, and what
you'll build next. Check the canonical planning tree at
simon-projects/.docs/planning/projects/saimon/slice_dependency_tree.json
for the authoritative slice state.
```


```
You are working in the Saimon repository (sv-copilot/saimon).

Read AGENTS.md and .docs/project_intake.json for the full project
contract. The canonical planning tree lives at
simon-projects/.docs/planning/projects/saimon/slice_dependency_tree.json
— that is the authoritative source for what's been built and what
comes next.

Current state:
- research_shared/ is built (9 modules: envelope, llm, db, auth,
  resilience, audit, self_extend, seed_data, seed_loader).
- 16 of 16 slices merged (all mergeable) + SHADOW-SEARCH-1 built (ready for PR)
- All 6 MCPs wired to LLM/DB backends with dependency injection
- 616 tests passing, ruff clean, compileall OK
- Runtime self-extension: unknown types → research → auto-register via SelfExtender
- DB re-seed resilience: SeedLoader loads canonical data on demand
- Shadow library integration: search_shadow_libraries, 5 adapters, dedup, verify
- All 4 success criteria from project_intake.json met

Next: TBD — check .docs/project_intake.json

Follow the Session Startup Protocol in AGENTS.md: consolidate prior
work, tree-sync after each merge, then start the next slice from the
planning tree. Follow TDD (RED → GREEN → REFACTOR → PROVE).

Branch: ai-dev
Python: python3.11 (via pyenv or system)

Begin by reading AGENTS.md, then tell me what you see and what
you'll build next.
```
