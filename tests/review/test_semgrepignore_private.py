"""Security scans must stay off private and generated data (P10-6): every private path that .gitignore keeps out of
git is also in .semgrepignore, so a scan never reads it."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PRIVATE = [
    ".venv/", ".snapshots/", "transcripts/", "profiles.json", "profiles.json.*",
    "santa/web/.cache/", "santa/web/debug_audio/", "evals/backup/",
    "local/", "notes/", ".env", ".env.*", "*_VULNHUNT_RESULTS_*/", "certs/", "tests/**/out/", "tools/**/out/",
]


def _rules(name):
    out = set()
    for line in (ROOT / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line.lstrip("/"))
    return out


@pytest.mark.parametrize("rule", PRIVATE)
def test_private_path_is_in_semgrepignore(rule):
    assert rule in _rules(".semgrepignore"), f"{rule} missing from .semgrepignore"


@pytest.mark.parametrize("rule", [r for r in PRIVATE if r != ".venv/"])
def test_semgrepignore_private_path_is_also_gitignored(rule):
    assert rule in _rules(".gitignore"), f"{rule} is in .semgrepignore but not in .gitignore"
