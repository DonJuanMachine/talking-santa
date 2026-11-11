#!/usr/bin/env bash
# Stops everything scripts/start-santa.sh started:  scripts/stop-santa.sh
# Stops Santa's page, frees the model's memory, and offers to quit Docker if the start script opened it.
set -uo pipefail
umask 077
cd "$(dirname "$0")/.."
RUN="${SANTA_LOCAL_DIR:-$PWD/local}/run"
ask() { local a; read -r -p "$1 [y/N] " a; [[ "$a" =~ ^[Yy] ]]; }
santa_pid() { # santa_pid <pid>: true if pid is a running Santa server (or its launcher) owned by you
  [[ "$1" =~ ^[0-9]+$ ]] || return 1
  [ "$(ps -o uid= -p "$1" 2>/dev/null | tr -d ' ')" = "$(id -u)" ] || return 1
  ps -o command= -p "$1" 2>/dev/null | grep -q -- "-m santa\.web"
}

if [ -f "$RUN/server.pid" ]; then
  pid=$(cat "$RUN/server.pid")
  if santa_pid "$pid"; then              # never signal a PID that is not Santa (stale file, reused PID, bad content)
    pkill -TERM -P "$pid" 2>/dev/null; kill -TERM "$pid" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && { pkill -KILL -P "$pid" 2>/dev/null; kill -KILL "$pid" 2>/dev/null; }
    echo "✓ Santa's page stopped"
  else echo "✓ Santa's page was not running"; fi
  rm -f "$RUN/server.pid"
else echo "✓ Santa's page was not started by start-santa.sh"; fi

if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  docker model unload --all >/dev/null 2>&1 && echo "✓ Model unloaded from memory"
  if [ -f "$RUN/started-docker" ]; then
    ask "Docker Desktop was opened by start-santa.sh. Quit it too?" && osascript -e 'quit app "Docker"' && echo "✓ Docker quit"
    rm -f "$RUN/started-docker"
  fi
fi
echo "Done."
