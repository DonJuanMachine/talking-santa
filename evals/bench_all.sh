#!/bin/bash
# Full bake-off: generate for each model, optionally judge, write report.
#
#   evals/bench_all.sh [--judge JUDGE_MODEL] model1 model2 ...
#   JUDGE_MODEL=... evals/bench_all.sh model1 model2 ...      (same thing, via environment)
#
# Existing results are MOVED (never deleted) to evals/backup/<YYYYmmdd-HHMM>/ before the new run.
# With no judge model the judge step is skipped (judging can be done outside the local models);
# judge.json then starts empty and the report says the judge model is "unrecorded".
# Exits non-zero if any gen or the judge step failed (the report is still written, without that model).
# Tip: BENCH_TAG=+v2 labels the results file with the persona version.
cd "$(dirname "$0")/.."
PY=.venv/bin/python

JUDGE="${JUDGE_MODEL:-}"
if [ "${1:-}" = "--judge" ]; then JUDGE="${2:-}"; shift 2 2>/dev/null || shift $#; fi
if [ "$#" -eq 0 ]; then
  echo "usage: evals/bench_all.sh [--judge JUDGE_MODEL] model [model ...]" >&2
  exit 2
fi

shopt -s nullglob
old=(evals/results/*.json)
if [ "${#old[@]}" -gt 0 ]; then
  dest="evals/backup/$(date +%Y%m%d-%H%M)"
  [ -e "$dest" ] && dest="$dest-$$"
  mkdir -p "$dest" && mv "${old[@]}" "$dest"/ || { echo "could not back up old results to $dest; aborting" >&2; exit 1; }
  echo "old results moved to $dest"
fi

fail=0
failed_models=()
for m in "$@"; do
  if ! $PY evals/bench.py gen "$m"; then
    echo "FAILED gen $m" >&2
    failed_models+=("$m")
    fail=1
  fi
done
if [ -n "$JUDGE" ]; then
  $PY evals/bench.py judge "$JUDGE" || { echo "FAILED judge" >&2; fail=1; }
else
  echo "no judge model given: skipping the judge step"
fi
$PY evals/bench.py report
$PY evals/bench.py manifest
if [ "$fail" -ne 0 ]; then
  echo "BENCH_FAILED (missing from the report: ${failed_models[*]:-judge step only})" >&2
  exit 1
fi
echo BENCH_DONE
