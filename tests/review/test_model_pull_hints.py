"""Every "docker model pull" a user is told to run names Santa's default model (or the variable that holds it), so a
hint never downloads a model Santa does not use. docs/history/ and CHANGELOG.md are records and are exempt; so is
docs/model-selection.md, which documents the candidates that were compared."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = re.search(r'MODEL = os\.getenv\("SANTA_MODEL", "([^"]+)"\)', (ROOT / "santa/config.py").read_text()).group(1)
ALLOWED = {DEFAULT, '"$MODEL"', "{config.MODEL}"}
EXEMPT = ("docs/history/", "CHANGELOG.md", "docs/model-selection.md")


def _tracked():
    if not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p and not p.startswith(EXEMPT)]


def test_default_model_is_gemma4_e4b():
    assert DEFAULT == "ai/gemma4:e4b"


def test_every_pull_hint_names_the_default_model():
    bad = []
    for rel in _tracked():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for name in re.findall(r"docker model pull\s+(\S+?)(?:\)|\s|$)", line):
                if name not in ALLOWED:
                    bad.append(f"{rel}:{i}: {name}")
    assert not bad, bad
