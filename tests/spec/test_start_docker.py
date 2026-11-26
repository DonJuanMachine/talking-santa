"""scripts/start-santa.sh, step 3 (Docker Desktop), against a fake `docker` command.

Seen on a real Mac: Docker Desktop was open and Model Runner answered, but the Docker engine took a minute per request
and then failed (HTTP 500). The script said "Docker Desktop is not running", offered to start it, and sat at
"waiting for Docker" with no progress, because each `docker info` hung and the wait only counted its own sleeps.
Now every engine check has a time limit, the wait counts clock time, and an open Docker Desktop whose engine does not
answer is reported as such, with an offer to restart it.

The fake `docker` and `open` only write to a scratch folder; nothing here starts Docker or Santa."""
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FAKE_DOCKER = r"""#!/bin/bash
D="$FAKE_DIR"
echo "$*" >> "$D/calls"
case "$1 ${2:-}" in
  "info "*)
    if [ -f "$D/engine_ok" ]; then echo ok; exit 0; fi
    if [ -f "$D/starting" ]; then n=$(( $(cat "$D/starting") - 1 )); echo "$n" > "$D/starting"
      [ "$n" -le 0 ] && touch "$D/engine_ok"; exit 1; fi
    exec sleep 30 ;;
  "desktop status") printf 'Name                Value\nStatus              %s\n' "$(cat "$D/state")" ;;
  "desktop restart") touch "$D/engine_ok" ;;
  *) exit 1 ;;
esac
"""


def run(state, engine_ok=False, starting=None, answers=""):
    tmp = Path(tempfile.mkdtemp(prefix="santa-docker-"))
    fake, local, home = tmp / "bin", tmp / "local", tmp / "home"
    for d in (fake, local, home):
        d.mkdir()
    (fake / "docker").write_text(FAKE_DOCKER)
    (fake / "open").write_text('#!/bin/bash\necho "open $*" >> "$FAKE_DIR/calls"\n')
    for f in ("docker", "open"):
        (fake / f).chmod(0o755)
    (tmp / "state").write_text(state)
    if engine_ok:
        (tmp / "engine_ok").touch()
    if starting is not None:
        (tmp / "starting").write_text(str(starting))
    env = {"PATH": f"{fake}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home), "FAKE_DIR": str(tmp),
           "SANTA_LOCAL_DIR": str(local), "SANTA_PYTHON": sys.executable, "SANTA_DOCKER_CHECK_S": "1",
           "SANTA_BASE_URL": "http://127.0.0.1:9/v1", "SANTA_OPEN": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    t0 = time.monotonic()
    p = subprocess.run(["bash", str(ROOT / "scripts/start-santa.sh")], env=env, input=answers, capture_output=True,
                       text=True, timeout=120)
    calls = (tmp / "calls").read_text().splitlines() if (tmp / "calls").exists() else []
    out = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)     # the script colors ✓ and ✗
    return out, calls, time.monotonic() - t0


def test_healthy_engine_passes_straight_through():
    out, calls, _ = run("running", engine_ok=True, answers="n\n")
    assert "✓ Docker Desktop is running" in out
    assert "desktop status" not in calls and "desktop restart" not in calls
    assert "Docker Model Runner is not answering" in out          # the next step ran (our fake runner is down)


def test_open_but_unresponsive_engine_is_named_and_not_restarted_without_a_yes():
    out, calls, took = run("running", answers="n\n")
    assert "Docker Desktop is open (running), but its engine is not responding" in out
    assert "Docker Desktop is not running" not in out
    assert "Restart Docker Desktop (whale menu > Restart)" in out
    assert "desktop restart" not in calls and not any(c.startswith("open") for c in calls)
    assert took < 20, took                                        # the hung `docker info` was cut off, not waited out


def test_yes_restarts_docker_and_carries_on():
    out, calls, _ = run("running", answers="y\nn\n")
    assert "desktop restart" in calls
    assert "✓ Docker Desktop is running" in out
    assert "Docker Model Runner is not answering" in out
    assert not any(c.startswith("open") for c in calls)


def test_starting_docker_is_waited_for_without_a_question():
    out, calls, _ = run("starting", starting=2, answers="n\n")
    assert "Docker Desktop is still starting" in out
    assert "✓ Docker Desktop is running" in out
    assert "desktop restart" not in calls


def test_stopped_docker_is_offered_a_start():
    out, calls, took = run("stopped", answers="n\n")
    assert "✗ Docker Desktop is not running" in out
    assert "Santa needs Docker Desktop" in out
    assert not any(c.startswith("open") for c in calls)
    assert took < 20, took
