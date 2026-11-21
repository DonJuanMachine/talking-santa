"""The setup steps make local/ private, and SECURITY.md does not claim more privacy than the code gives.

Santa creates its own files owner-only (tests/spec/test_private_files.py), but a file you copy or edit yourself
(`cp profiles.example.json local/profiles.json`, `local/santa.env` with the PIN) keeps your umask's mode (usually 0644)
until Santa next saves it. So every documented `mkdir -p local` also runs `chmod 700 local`, and SECURITY.md says
which files are private and which are not.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETUP_DOCS = ["README.md", "CONTRIBUTING.md", "local.example/README.md"]
MKDIR_LOCAL = re.compile(r"mkdir -p local(?![/\w])")


def _mkdir_lines(rel):
    return [(n, line) for n, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1)
            if MKDIR_LOCAL.search(line)]


@pytest.mark.parametrize("rel", SETUP_DOCS)
def test_every_mkdir_local_also_makes_it_private(rel):
    lines = _mkdir_lines(rel)
    assert lines, f"{rel}: no `mkdir -p local` found (update this test if the setup moved)"
    bad = [f"{rel}:{n}" for n, line in lines if "chmod 700 local" not in line]
    assert bad == [], bad


def _privacy_bullet():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    bullets = " ".join(text.split()).split(" - ")
    hits = [b for b in bullets if "0600" in b]
    assert len(hits) == 1, hits
    return hits[0]


def test_security_says_files_you_make_yourself_are_not_covered():
    bullet = _privacy_bullet()
    assert "yourself" in bullet and "next saves" in bullet, bullet


def test_security_points_at_the_chmod_step():
    assert "chmod 700 local" in _privacy_bullet()
