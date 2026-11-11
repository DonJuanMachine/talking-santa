#!/usr/bin/env bash
# Local security scan for talking-santa. Run from anywhere:
#   bash scripts/security-scan.sh [--with-snyk-code]
# Reports go OUTSIDE the repo: ~/Documents/security-reports/talking-santa/<timestamp>/
# Snyk Code (uploads source to Snyk's cloud) is OFF unless --with-snyk-code is passed.
set -uo pipefail
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HOME/Documents/security-reports/talking-santa/$(date +%Y-%m-%d_%H%M%S)"
WITH_SNYK_CODE=false
[ "${1:-}" = "--with-snyk-code" ] && WITH_SNYK_CODE=true
mkdir -p "$OUT"
cd "$ROOT"

declare_result() { printf '%-12s %s\n' "$1" "$2" | tee -a "$OUT/SUMMARY.txt"; }
run() {  # run <name> <cmd...>   (tool missing => SKIPPED; nonzero exit => FINDINGS/ERROR)
  local name="$1"; shift
  if ! command -v "$1" >/dev/null 2>&1; then declare_result "$name" "SKIPPED (not installed)"; return; fi
  "$@" >"$OUT/$name.txt" 2>&1
  local rc=$?
  if [ $rc -eq 0 ]; then declare_result "$name" "clean"; else declare_result "$name" "exit $rc - review $OUT/$name.txt"; fi
}

echo "Scanning $ROOT"; echo "Reports: $OUT"; echo

# 1. Secrets - working tree AND git history (profiles.json is gitignored, so excluded from history scan too)
run gitleaks-tree    gitleaks detect --source . --no-git --redact --no-banner
run gitleaks-history gitleaks detect --source . --redact --no-banner

# 2. Dependency CVEs (two databases)
run pip-audit  pip-audit -r requirements.txt
# snyk's pip scan spawns a bare `python` (absent on macOS) and needs the deps installed: use the project venv
SNYK_PY="$ROOT/.venv/bin/python"; [ -x "$SNYK_PY" ] || SNYK_PY=python3
run snyk-deps  snyk test --file=requirements.txt --package-manager=pip --command="$SNYK_PY"

# 3. Static analysis of own code
run bandit   bandit -r . -x ./.venv,./tests,./tools,./evals,./.snapshots -ll
run semgrep  semgrep --config auto --quiet --error .

# 4. Broad sweep
run trivy trivy fs --scanners vuln,secret,misconfig --skip-dirs .venv --skip-dirs .snapshots --skip-dirs tools/probes/out --skip-dirs tools/audit/experiments/out --skip-dirs evals/backup .

# 5. Cloud SAST: opt-in only
if $WITH_SNYK_CODE; then run snyk-code snyk code test; else declare_result snyk-code "SKIPPED (opt-in: --with-snyk-code)"; fi

echo; echo "Done. Summary: $OUT/SUMMARY.txt"
