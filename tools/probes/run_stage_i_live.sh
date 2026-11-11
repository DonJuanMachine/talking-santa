#!/bin/zsh
# Stage I live runs, in the pre-registered order: arc ON (Arm A), control (SANTA_ARC=0), pooled recall x5, summary.
# Refuses to start while the web app is running (it keeps the model busy and would skew TTFT).
set -u
cd "$(dirname "$0")/../.."
PY=~/.venvs/talking-santa-h/bin/python
export PYTHONDONTWRITEBYTECODE=1
unset SANTA_ARC SANTA_TEMP SANTA_MAX_TOKENS SANTA_MODEL SANTA_FILTER
if pgrep -f 'python.* -m santa.web' >/dev/null; then
  echo "santa.web is running: stop it first (Ctrl-C in its terminal)." >&2
  exit 2
fi
docker model unload --all
$PY tools/probes/smoke_live.py --tag I || exit 1
$PY tools/probes/smoke_live.py --tag I --control || exit 1
for i in 1 2 3 4 5; do
  $PY tools/probes/smoke_live.py --tag I-recall-$i --only 2
done
docker model unload --all
$PY tools/probes/smoke_live.py --tag I-summary | tee tools/probes/out/smoke_live_I_summary.txt
