"""Call log: when each registered child talked with Santa on the call page. Names, dates and times only.

local/calls.json: {"calls": {"Emma": ["2026-11-22T18:05", ...]}}, oldest first, at most MAX_PER_CHILD per child.
No words, no audio. Only real calls write it (the call page, santa/web); chat.py never does. A child is logged once per
call, when their MIN_TURNS-th turn ends, with the time of their first turn, so a dropped connection is logged too.
Santa sees only the active child's entries, as a short note on that child's turn (persona.calls_note).
SANTA_CALL_LOG=0 turns it off (nothing read, nothing written)."""
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import config

MAX_PER_CHILD = 50
MIN_TURNS = 2
FMT = "%Y-%m-%dT%H:%M"


def enabled() -> bool:
    return os.getenv("SANTA_CALL_LOG", "1").strip() != "0"


def _warn(msg: str) -> None:
    print(f"\n!!! WARNING (call log): {msg}\n", file=sys.stderr, flush=True)


def _path(path) -> Path:
    return Path(path) if path is not None else Path(config.CALLS_PATH)


def _read(path: Path) -> dict[str, list[str]]:
    data = json.loads(path.read_text())
    calls = data.get("calls") if isinstance(data, dict) else None
    if not isinstance(calls, dict):
        raise ValueError("top level has no 'calls' object")
    out: dict[str, list[str]] = {}
    for name, times in calls.items():
        good = []
        for t in times if isinstance(times, list) else []:
            try:
                good.append(datetime.strptime(t, FMT).strftime(FMT))
            except (TypeError, ValueError):
                continue                                  # a hand-edited bad entry is skipped, not fatal
        if good:
            out[str(name)] = sorted(good)[-MAX_PER_CHILD:]
    return out


def _load_raw(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        return _read(path)
    except (ValueError, OSError) as e:
        _warn(f"{path.name} is unreadable ({e}); starting a new call log. The broken file is kept as "
              f"{path.name}.corrupt.")
        try:
            corrupt = path.with_name(path.name + ".corrupt")
            shutil.copyfile(path, corrupt)
            os.chmod(corrupt, 0o600)
        except OSError:
            pass
        return {}


def load(path=None) -> dict[str, list[datetime]]:
    """{child: [datetime, ...]} oldest first. Never raises."""
    try:
        raw = _load_raw(_path(path))
    except Exception as e:                                # never let the log stop a call
        _warn(f"could not read the call log ({e})")
        return {}
    return {name: [datetime.strptime(t, FMT) for t in times] for name, times in raw.items()}


def _write(path: Path, data: dict[str, list[str]]) -> None:
    """Atomic and private: a temp file (mode 600) in the same folder, then os.replace."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"calls": data}, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def record(name: str, when: datetime, path=None) -> bool:
    """Add one call for `name` at `when` (to the minute), keeping the newest MAX_PER_CHILD. Fails soft."""
    p = _path(path)
    try:
        data = _load_raw(p)
        times = data.get(name, []) + [when.strftime(FMT)]
        data[name] = sorted(times)[-MAX_PER_CHILD:]
        _write(p, data)
        return True
    except Exception as e:
        _warn(f"could not save the call log ({e})")
        return False


def remove(path=None) -> None:
    """Used by /forget: delete the log and any temp or broken copy of it."""
    p = _path(path)
    for f in (p, p.with_name(p.name + ".tmp"), p.with_name(p.name + ".corrupt")):
        try:
            f.unlink()
        except OSError:
            pass
