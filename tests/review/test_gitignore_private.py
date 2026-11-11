"""Private and generated files are ignored at any depth (P10-5). Runs `git check-ignore` in a temp repo that holds a
copy of the repo's .gitignore, with its own HOME so no personal git config or global ignore file can interfere."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

IGNORED = [
    "profiles.json", "santa/profiles.json", "tests/profiles.json", "santa/profiles.json.bak", "profiles.json.1",
    "transcripts/x", "santa/web/transcripts/x",
    "x.pem", "a/b/x.pem", "x.key", "a/x.key", "x.p12", "a/x.p12",
    "x.m4a", "a/x.m4a", "x.log", "a/b/x.log", "x.sqlite", "a/x.sqlite", "x.db", "a/x.db",
    "santa.env", "cfg/santa.env",
    "local/profiles.json", ".env", ".env.local",
]
NOT_IGNORED = [
    "local.example/santa.env.example", "santa.env.example", ".env.example", "docs/x.md", "santa/ok.py",
    "docs/profiles-notes.md", "tests/test_profiles.py",
]


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    base = tmp_path_factory.mktemp("gi")
    (base / "home").mkdir()
    (base / "gitconfig").write_text("")
    shutil.copy(ROOT / ".gitignore", base / ".gitignore")
    r = _git(base, "init", "-q")
    assert r.returncode == 0, r.stderr
    return base


def _git(base, *args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(base / "home"),
           "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=base, env=env, capture_output=True, text=True)


@pytest.mark.parametrize("path", IGNORED)
def test_private_or_generated_path_is_ignored(repo, path):
    assert _git(repo, "check-ignore", "-q", "--no-index", path).returncode == 0, path


@pytest.mark.parametrize("path", NOT_IGNORED)
def test_examples_and_ordinary_files_are_not_ignored(repo, path):
    assert _git(repo, "check-ignore", "-q", "--no-index", path).returncode == 1, path
