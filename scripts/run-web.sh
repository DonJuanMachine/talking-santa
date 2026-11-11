#!/usr/bin/env bash
# Start Santa's call page.
#   scripts/run-web.sh              this Mac only:   http://127.0.0.1:8765
#   scripts/run-web.sh --network    home Wi-Fi too:  https://<this Mac>.local:8765 (PIN from local/santa.env)
# Personal settings come from local/santa.env (gitignored). caffeinate keeps the Mac awake while Santa runs.
# SANTA_PYTHON overrides the interpreter (default: the venv from the README).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${SANTA_PYTHON:-$HOME/.venvs/talking-santa-h/bin/python}"
exec caffeinate -i env HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 "$PY" -m santa.web "$@"
