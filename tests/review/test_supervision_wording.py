"""The supervision requirement is worded one way everywhere, and the README states it before "What you need".
"Should be nearby" is weaker than the design assumption (an adult in the room during every call), so it must not
come back in a public doc."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PHRASE = "an adult stays in the room for every call"
PUBLIC = [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "CONTRIBUTING.md", ROOT / "local.example" / "README.md",
          *sorted((ROOT / "docs").glob("*.md"))]


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


@pytest.mark.parametrize("path", PUBLIC, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_weaker_wording(path):
    assert "should be nearby" not in _flat(path)


def test_readme_states_it_before_what_you_need():
    intro = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split("## What you need")[0].split()).lower()
    assert PHRASE in intro


@pytest.mark.parametrize("name", ["SECURITY.md", "docs/architecture.md"])
def test_security_and_architecture_use_the_same_phrase(name):
    assert PHRASE in _flat(ROOT / name)
