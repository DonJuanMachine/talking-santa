"""No committed file holds an absolute home-folder path, which would publish the account name (P2-10, P11-2).

Placeholders such as /Users/<you>/ or $HOME are fine; a real-looking name after /Users/, /home/ or in a
Claude Code scratch path (-Users-NAME-) is not.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOME_PATH = re.compile(
    r"/Users/(?![<${*]|Shared/|you\b|name\b|user\b|USER\b)[A-Za-z0-9._-]+"
    r"|/home/(?![<${*]|user\b|USER\b|runner\b|you\b)[A-Za-z0-9._-]+"
    r"|-Users-(?![<{])[A-Za-z0-9._]+-"
)


def _tracked_text_files() -> list[Path]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    files = []
    for name in out.split("\0"):
        p = ROOT / name
        if name and p.is_file():
            try:
                p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            files.append(p)
    return files


def test_no_committed_file_contains_an_absolute_home_path():
    hits = []
    for p in _tracked_text_files():
        if p.resolve() == Path(__file__).resolve():
            continue                                             # its own examples below
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if HOME_PATH.search(line):
                hits.append(f"{p.relative_to(ROOT)}:{n}")      # location only, never the matched text
    assert hits == [], "absolute home paths (replace with <venv>, ~ or $HOME): " + ", ".join(hits)


@pytest.mark.parametrize("ok", ["/Users/<you>/projects", "$HOME/projects", "~/.venvs/x", "/Users/Shared/x",
                                "-Users-<user>-projects"])
def test_placeholders_are_allowed(ok):
    assert not HOME_PATH.search(ok)


@pytest.mark.parametrize("bad", ["/Users/alice/projects", "/home/bob/x", "/tmp/claude-501/-Users-carol-projects-x"])
def test_real_looking_paths_are_caught(bad):
    assert HOME_PATH.search(bad)
