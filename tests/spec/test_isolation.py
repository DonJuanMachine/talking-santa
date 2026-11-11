"""The suite must never reach the real profiles file, whatever the shell exports (P6-8).
Paths are compared only; the real file is never opened, and nothing here writes to it."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from tests._real_paths import ROOT, real_profiles_paths


def _child(code_or_args, real: Path, local_dir=None, module=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SANTA_")}
    env["SANTA_PROFILES"] = str(real)
    if local_dir:
        env["SANTA_LOCAL_DIR"] = local_dir
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, *code_or_args], env=env, capture_output=True, text=True, cwd=str(ROOT))


def test_support_redirects_an_exported_real_profiles_path():
    real = sorted(real_profiles_paths())[0]
    code = ("import sys; sys.path.insert(0, '.'); import tests.spec._support; from santa import config; "
            "print(config.PROFILES_PATH.resolve())")
    r = _child(["-c", code], real)
    assert r.returncode == 0, r.stderr[-500:]
    assert Path(r.stdout.strip()).resolve() not in real_profiles_paths()


def test_pytest_on_one_spec_file_ignores_exported_real_path():
    real = sorted(real_profiles_paths())[0]
    r = _child(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/spec/probe_isolation_target.py"], real,
               local_dir=str(ROOT / "local"))
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]


def test_this_run_uses_temp_locations():
    from santa import config, local
    tmp = Path(tempfile.gettempdir()).resolve()
    assert config.PROFILES_PATH.resolve() not in real_profiles_paths()
    assert local.LOCAL_DIR.resolve() != (ROOT / "local").resolve()
    assert tmp in config.PROFILES_PATH.resolve().parents
