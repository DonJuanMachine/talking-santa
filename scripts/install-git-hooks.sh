#!/usr/bin/env bash
# Installs the repo's git hooks (re-run after editing scripts/git-hooks/*).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS="$(git -C "$ROOT" rev-parse --git-path hooks)"
case "$HOOKS" in /*) ;; *) HOOKS="$ROOT/$HOOKS" ;; esac
for h in "$ROOT"/scripts/git-hooks/*; do
  install -m 755 "$h" "$HOOKS/$(basename "$h")"
  echo "installed $(basename "$h") -> $HOOKS"
done
