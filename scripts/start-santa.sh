#!/usr/bin/env bash
# One command to get Santa ready:  scripts/start-santa.sh [--network]
# Checks everything Santa needs, offers to fix what is off (answer y or n), then starts the call page in the
# background and opens it. Stop everything again with scripts/stop-santa.sh.
# SANTA_OPEN=0 starts Santa without opening the browser.
set -uo pipefail
umask 077                       # files this script creates (log, PID file) are private to you
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="${SANTA_PYTHON:-$HOME/.venvs/talking-santa-h/bin/python}"
NETWORK=""; [ "${1:-}" = "--network" ] && NETWORK=1

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
note() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mSanta is not ready:\033[0m %s\n' "$*"; exit 1; }
ask()  { local a; read -r -p "    $1 [y/N] " a; [[ "$a" =~ ^[Yy] ]]; }
limit() { # limit <seconds> <command...>: run the command; fail if it has not finished after <seconds>
  local s="$1"; shift
  "$@" & local pid=$!
  ( sleep "$s"; kill -TERM "$pid" 2>/dev/null ) 2>/dev/null & local guard=$!
  wait "$pid"; local rc=$?
  pkill -P "$guard" 2>/dev/null; kill "$guard" 2>/dev/null; wait "$guard" 2>/dev/null
  return "$rc"
}
wait_for() { # wait_for "<what>" <seconds> <command...>: retry until it works or <seconds> of clock time have passed
  local what="$1" end=$((SECONDS + $2)); shift 2
  printf '    waiting for %s ' "$what"
  while [ "$SECONDS" -lt "$end" ]; do "$@" >/dev/null 2>&1 && { echo; return 0; }; printf '.'; sleep 2; done
  echo; return 1
}
# A healthy Docker engine answers `docker info` in about a second. A broken one can hang for a minute and then fail,
# so every engine check has a time limit (SANTA_DOCKER_CHECK_S).
CHECK_S="${SANTA_DOCKER_CHECK_S:-15}"
docker_up() { limit "$CHECK_S" docker info >/dev/null 2>&1; }
desktop_state() { # running, starting, stopped, ... as Docker Desktop reports it; empty if it cannot say
  local s
  s=$(limit 10 docker desktop status 2>/dev/null | awk '$1 == "Status" {print $2; exit}')
  if [ -z "$s" ] && pgrep -f "Docker.app/Contents/MacOS/com.docker.backend" >/dev/null 2>&1; then s=running; fi
  echo "$s"
}

echo "Checking Santa's setup..."

# 1. Python environment (also reads your settings below, so it comes first)
if [ -x "$PY" ]; then ok "Python environment"; else
  bad "Python environment not found at $PY"
  die "Do the one-time install in README.md (\"One-time install\"), then run this again."
fi

# Settings from local/santa.env, read by the same parser Santa uses (santa/local.py). A value already in your
# shell wins. The output is shell-quoted, so no setting can run a command here.
exports=$("$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); from santa import local; print(local.shell_exports())' \
  "$ROOT") || die "Could not read your settings (local/santa.env)."
eval "$exports"
if [ -n "${SANTA_PYTHON:-}" ] && [ "$SANTA_PYTHON" != "$PY" ]; then         # set in santa.env: check it too
  PY="$SANTA_PYTHON"; [ -x "$PY" ] || die "SANTA_PYTHON in local/santa.env is not a program: $PY"
fi
MODEL="${SANTA_MODEL:-ai/gemma4:e4b}"
BASE="${SANTA_BASE_URL:-http://localhost:12434/engines/v1}"
PORT="${SANTA_PORT:-8765}"
TTS="${SANTA_TTS:-kokoro}"
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] \
  || die "SANTA_PORT must be a number from 1 to 65535 (it is: $PORT)."
[[ "$BASE" =~ ^https?:// ]] || die "SANTA_BASE_URL must start with http:// or https:// (it is: $BASE)."

RUN="$LOCAL/run"; mkdir -p "$RUN"
for d in "$LOCAL" "$RUN"; do [ -O "$d" ] && chmod 700 "$d"; done   # other accounts on this Mac cannot look in

runner_up() { curl -sf -m 3 -- "$BASE/models" >/dev/null; }
santa_pid() { # santa_pid <pid>: true if pid is a running Santa server (or its launcher) owned by you
  [[ "$1" =~ ^[0-9]+$ ]] || return 1
  [ "$(ps -o uid= -p "$1" 2>/dev/null | tr -d ' ')" = "$(id -u)" ] || return 1
  ps -o command= -p "$1" 2>/dev/null | grep -q -- "-m santa\.web"
}
port_answers() { # anyone listening on the port, from any account (lsof only sees your own processes)
  nc -z -G 1 127.0.0.1 "$PORT" >/dev/null 2>&1 || nc -z -G 1 ::1 "$PORT" >/dev/null 2>&1
}
listener_is() { # listener_is <pid>: the process listening on the port is <pid> or its child
  local p pp
  for p in $(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null); do
    [ "$p" = "$1" ] && return 0
    pp=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
    [ "$pp" = "$1" ] && return 0
  done
  return 1
}
page_up() { curl -skf -m 3 "http://127.0.0.1:$PORT/" >/dev/null || curl -skf -m 3 "https://localhost:$PORT/" >/dev/null; }

# 2. Already running?
if [ -f "$RUN/server.pid" ] && santa_pid "$(cat "$RUN/server.pid")"; then
  ok "Santa is already running (stop it with scripts/stop-santa.sh)"; exit 0
fi
rm -f "$RUN/server.pid"

# 3. Docker Desktop
if ! command -v docker >/dev/null; then die "Docker is not installed. Install Docker Desktop first."; fi
if docker_up; then ok "Docker Desktop is running"; else
  state=$(desktop_state)
  case "$state" in
    ""|stopped)
      bad "Docker Desktop is not running"
      ask "Start Docker Desktop now?" || die "Santa needs Docker Desktop for her brain."
      open -a Docker && touch "$RUN/started-docker"
      wait_for "Docker" 180 docker_up || die "Docker did not start in time. Open it by hand and run this again." ;;
    starting)
      bad "Docker Desktop is still starting"
      wait_for "Docker" 180 docker_up || die "Docker did not finish starting. Open it by hand and run this again." ;;
    *)
      bad "Docker Desktop is open ($state), but its engine is not responding"
      ask "Restart Docker Desktop now? (containers you have running will restart too)" \
        || die "Restart Docker Desktop (whale menu > Restart), then run this again."
      limit 180 docker desktop restart >/dev/null 2>&1
      wait_for "Docker" 180 docker_up \
        || die "Docker's engine still does not respond. Quit Docker Desktop from the whale menu, open it again, then run this again." ;;
  esac
  ok "Docker Desktop is running"
fi

# 4. Model Runner
if runner_up; then ok "Docker Model Runner answers"; else
  bad "Docker Model Runner is not answering at $BASE"
  if ask "Turn on Model Runner (port 12434) now?"; then
    limit 60 docker desktop enable model-runner --tcp 12434 >/dev/null 2>&1 || true
    wait_for "Model Runner" 60 runner_up || true
  fi
  runner_up || die "Turn it on in Docker Desktop > Settings > Model Runner > enable host-side TCP (port 12434), then run this again."
  ok "Docker Model Runner answers"
fi

# 5. Santa's model downloaded?
model_listed() { limit 60 docker model ls 2>/dev/null | awk 'NR>1{print $1}' | grep -qx -- "${MODEL#ai/}"; }
if model_listed; then ok "Model $MODEL is downloaded"; else
  bad "Model $MODEL is not downloaded"
  ask "Download it now (a few GB, needs internet)?" && docker model pull "$MODEL"
  model_listed || die "Model $MODEL is missing."
  ok "Model $MODEL is downloaded"
fi

# 6. Only Santa's model in memory (two big models together run the Mac out of GPU memory)
others=$(limit 60 docker model ps 2>/dev/null | awk -v m="${MODEL#ai/}" 'NR>1 && $1!=m {print $1}')
if [ -n "$others" ]; then
  bad "Another model is loaded in memory: $(echo $others)"
  if ask "Unload it so Santa has room?"; then limit 60 docker model unload --all >/dev/null 2>&1; ok "Memory cleared"
  else note "Continuing; if Santa fails with 'Compute error', run: docker model unload --all"; fi
else ok "No competing models in memory"; fi

# 7. Santa's voice
if [ "$TTS" = pocket ]; then
  if [ -d "$HOME/.cache/huggingface/hub/models--kyutai--pocket-tts-without-voice-cloning" ]; then
    ok "Voice: Pocket TTS (${SANTA_VOICE:-peter_yearsley})"
  else die "Pocket TTS voice files are missing. See README (Pocket TTS) to fetch them once."; fi
else ok "Voice: Kokoro (${SANTA_VOICE:-am_michael})"; fi

# 8. Home-network extras
ARGS=()
if [ -n "$NETWORK" ]; then
  ARGS=(--network)
  pin="${SANTA_PIN:-}"
  [ -n "${pin//[[:space:]]/}" ] && ok "PIN is set" || die "Set SANTA_PIN=<6+ characters> in local/santa.env for --network."
  [ -f "$LOCAL/certs/santa.pem" ] && [ -f "$LOCAL/certs/santa-key.pem" ] && ok "HTTPS certificates" \
    || die "Certificates missing in $LOCAL/certs. See README > \"Use on your home network\" (mkcert)."
fi

# 9. Port free? lsof shows only your own processes, so an older Santa of yours can be stopped here; then a direct
#    connection test catches a listener from any other account, which this script cannot see or stop.
holder=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)
if [ -n "$holder" ]; then
  if santa_pid "$holder" || santa_pid "$(ps -o ppid= -p "$holder" 2>/dev/null | tr -d ' ')"; then
    bad "An older Santa (started by hand, pid $holder) is already using port $PORT"
    ask "Stop it and start fresh with your current settings?" || die "Close the other Santa first, then run this again."
    pkill -TERM -P "$holder" 2>/dev/null; kill -TERM "$holder" 2>/dev/null; sleep 2
  else
    die "Port $PORT is in use by another program (pid $holder). Stop it, or set SANTA_PORT in local/santa.env."
  fi
fi
port_answers && die "Port $PORT is in use by another program or another account on this Mac. Stop it, or set SANTA_PORT in local/santa.env."
ok "Port $PORT is free"

# Start
echo; echo "Starting Santa..."
: > "$RUN/santa.log"; chmod 600 "$RUN/santa.log"
nohup scripts/run-web.sh ${ARGS[@]+"${ARGS[@]}"} >> "$RUN/santa.log" 2>&1 &
SERVER=$!
echo "$SERVER" > "$RUN/server.pid"

# Ready only when the page answers AND the process listening on the port is the server just started
# (or its child): never trust whatever else might answer on the port.
printf "    waiting for Santa's page "
ready=""; n=120
while [ "$n" -gt 0 ]; do
  kill -0 "$SERVER" 2>/dev/null || break                      # the server stopped: no point waiting
  if listener_is "$SERVER" && page_up; then ready=1; break; fi
  printf '.'; sleep 2; n=$((n-2))
done; echo

if [ -n "$ready" ]; then
  if [ -n "$NETWORK" ]; then URL="https://$(scutil --get LocalHostName).local:$PORT"; else URL="http://127.0.0.1:$PORT"; fi
  printf '\n\033[32mSanta is ready:\033[0m %s\n' "$URL"
  echo "Log: local/run/santa.log     Stop: scripts/stop-santa.sh"
  [ -z "$NETWORK" ] && [ "${SANTA_OPEN:-1}" != 0 ] && open "$URL"
else
  tail -15 "$RUN/santa.log"; pkill -TERM -P "$SERVER" 2>/dev/null; kill "$SERVER" 2>/dev/null; rm -f "$RUN/server.pid"
  die "Santa's page did not come up. The log above says why (full log: local/run/santa.log)."
fi
