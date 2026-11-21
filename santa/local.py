"""Your personal files, kept out of git: one folder for everything that is yours, not the project's.

Default location: `local/` in the repo (gitignored). Set SANTA_LOCAL_DIR to keep it somewhere else.

    local/
      santa.env       your settings, KEY=VALUE per line (e.g. SANTA_PIN=...); see local.example/santa.env.example
      santa_world.txt Santa's backstory: home, wife, reindeer, elves (replaces the built-in one)
      santa.jpg       Santa's picture on the call page (.jpg, .jpeg, .png or .webp)
      profiles.json   the children Santa knows (names, ages, remembered facts)
      transcripts/    chat.py saves a transcript here whenever a typed session had at least one reply; /forget deletes them
      certs/          HTTPS certificate + key for `python -m santa.web --network`

The code in git only knows these file names. A missing file falls back to the project default (the painted Santa,
no PIN, and so on).
"""
import os
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = Path(os.getenv("SANTA_LOCAL_DIR", str(ROOT / "local"))).expanduser()
ENV_FILE = LOCAL_DIR / "santa.env"
CERTS_DIR = LOCAL_DIR / "certs"
WORLD_FILE = LOCAL_DIR / "santa_world.txt"
IMAGE_NAMES = ("santa.jpg", "santa.jpeg", "santa.png", "santa.webp")


_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INLINE_COMMENT = re.compile(r"\s#")


def _value(raw: str) -> str:
    """One value: quotes are removed ('...' or "..."); otherwise a comment that starts with " #" is dropped.
    A "#" with no space before it is part of the value, so a PIN like 48#29x is kept whole."""
    v = raw.strip()
    if v[:1] in ("'", '"'):
        end = v.find(v[0], 1)
        if end > 0:
            return v[1:end]
    m = _INLINE_COMMENT.search(raw)          # on the raw text: "KEY=   # note" is an empty value
    return (raw[:m.start()] if m else raw).strip()


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    """KEY=VALUE lines of a settings file. Blank lines and lines starting with # are skipped; `export KEY=...` works.
    This is the only parser: the shell scripts get their settings from it too (shell_exports)."""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if _KEY.fullmatch(key):
            out[key] = _value(value)
    return out


def load_env(path: Path = ENV_FILE) -> list[str]:
    """Read KEY=VALUE lines into the environment. Values already set in the shell win.

    Called by the programs you run (python -m santa.web, chat.py) before anything else reads settings. Never called
    on import, so tests never pick up your personal settings. Returns the keys it set.
    """
    set_keys = []
    for key, value in read_env(path).items():
        if key not in os.environ:
            os.environ[key] = value
            set_keys.append(key)
    return set_keys


def shell_exports(path: Path = ENV_FILE) -> str:
    """Shell lines for scripts/start-santa.sh: `export SANTA_X='...'` for each SANTA_* setting the shell does not
    already have, safely quoted for `eval`, plus LOCAL=<this folder>. SANTA_LOCAL_DIR is never exported from the file:
    it only works from the shell (the folder is chosen before the file can be read)."""
    lines = [f"LOCAL={shlex.quote(str(LOCAL_DIR))}"]
    for key, value in read_env(path).items():
        if key.startswith("SANTA_") and key != "SANTA_LOCAL_DIR" and key not in os.environ:
            lines.append(f"export {key}={shlex.quote(value)}")
    return "\n".join(lines)


def santa_world(path: Path | None = None) -> str | None:
    """Your own version of Santa's world (home, wife, reindeer, elves), if you wrote one."""
    p = path or WORLD_FILE
    try:
        return p.read_text() if p.is_file() else None
    except (OSError, UnicodeDecodeError):
        return None


def santa_image(local_dir: Path | None = None) -> Path | None:
    """Your Santa picture, if you added one."""
    d = local_dir or LOCAL_DIR
    for name in IMAGE_NAMES:
        p = d / name
        if p.is_file():
            return p
    return None


def profiles_path() -> Path:
    """local/profiles.json; an older profiles.json in the repo root is still used until you move it."""
    new, old = LOCAL_DIR / "profiles.json", ROOT / "profiles.json"
    return old if (old.exists() and not new.exists()) else new
