#!/usr/bin/env bash
# preflight.sh — the blocking gate. Run this before anything else.
#
# Every check here is blocking. If a check cannot run, that is a FAILURE, not a
# skip: a gate that hides a broken build is worse than no gate. The version of
# this file this project replaced had a security audit wired as
# `pip-audit … || echo "review above"`, which reports success either way.
#
# Usage:
#   scripts/preflight.sh            # all checks
#   scripts/preflight.sh --fast     # skip the ones that need extra tooling
#
# Exit: 0 all passed · 1 a check failed · 2 the gate could not run at all.

set -uo pipefail

FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

PASS=0
FAIL=0
SKIPPED_TOOLING=0

green() { printf '\033[32m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; }
bold()  { printf '\033[1m%s\033[0m\n' "$1"; }

# Run a check. Args: label, command...
check() {
  local label="$1"; shift
  bold "── $label"
  if "$@"; then
    green "   ok"
    PASS=$((PASS + 1))
  else
    red "   FAILED: $label"
    FAIL=$((FAIL + 1))
  fi
}

# A check whose tooling is absent. Not a skip: in --fast mode it is reported as
# skipped but the run is still not a pass; in full mode it is a failure.
check_needs() {
  local label="$1" tool="$2"; shift 2
  if command -v "$tool" >/dev/null 2>&1; then
    check "$label" "$@"
  elif [ "$FAST" = "1" ]; then
    red "   SKIPPED (no $tool): $label — install $tool for a full gate"
    SKIPPED_TOOLING=$((SKIPPED_TOOLING + 1))
  else
    red "   FAILED: $label — $tool is not installed, so this check cannot run"
    FAIL=$((FAIL + 1))
  fi
}

PY="${PYTHON:-python3}"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"

bold "Saimon preflight"
echo "   python: $($PY --version 2>&1)"
echo

# 1. Python syntax across the tree: catches a broken file before anything imports it.
check "python compiles" $PY -m compileall -q research_shared saimon_mcp plugins eval_harness tests scripts

# 2. Lint.
# Lints the same paths the project's own CI lints, plus scripts/, which is new
# public surface: this artifact's gate must be no weaker, and no noisier, than the
# one the project runs.
check_needs "ruff" ruff $PY -m ruff check research_shared saimon_mcp scripts

# 3. Dependencies install cleanly (the file an adopter runs).
check "requirements resolve" $PY -m pip install --dry-run -q -r requirements.txt

# 4. Security audit — blocking. No `|| echo`.
check_needs "pip-audit (blocking)" pip-audit $PY -m pip_audit -r requirements.txt --strict

# 5. The test suite.
check "pytest" $PY -m pytest tests -q

# 6. The published API contract still matches the app.
check "openapi spec validates" $PY scripts/validate_openapi_spec.py

# 7. The compose file is valid — client-side, so no daemon is needed.
check_needs "compose config" docker docker compose config --quiet

# 8. The adoption path: a stranger's first command must work with nothing configured.
check "adoption smoke (offline)" $PY scripts/adoption_smoke.py

# 9. This tree contains nothing it should not.
check "public tree is clean" $PY scripts/validate_public_tree.py

echo
bold "preflight: $PASS passed, $FAIL failed, $SKIPPED_TOOLING skipped for missing tooling"
if [ "$FAIL" -gt 0 ]; then
  red "preflight FAILED"
  exit 1
fi
if [ "$SKIPPED_TOOLING" -gt 0 ]; then
  red "preflight INCOMPLETE — $SKIPPED_TOOLING check(s) could not run (--fast); do not treat this as a pass"
  exit 1
fi
green "preflight passed"
