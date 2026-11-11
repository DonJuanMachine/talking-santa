"""Where the app would keep the real profiles file, computed by path only (nothing is opened or read).

Asks the app's own config code (santa.local.profiles_path) in a clean child process with every SANTA_* variable
removed, so an exported SANTA_LOCAL_DIR / SANTA_PROFILES cannot change the answer. profiles_path() only stats
the two candidate paths. Also returns both candidate locations.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def real_profiles_paths() -> set:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SANTA_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    out = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
         "from santa import local; print(local.profiles_path())", str(ROOT)],
        env=env, capture_output=True, text=True, check=True, cwd=str(ROOT),
    ).stdout.strip()
    return {Path(out).resolve(), (ROOT / "local" / "profiles.json").resolve(), (ROOT / "profiles.json").resolve()}
