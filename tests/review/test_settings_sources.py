"""docs/configuration.md is the one complete list of settings. local.example/santa.env.example is a short template;
the docs must not call it complete unless it is, and it must point at the complete list."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = (ROOT / "local.example" / "santa.env.example").read_text(encoding="utf-8")
CONFIG = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
README = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
NAME = re.compile(r"\bSANTA_[A-Z0-9_]+\b")


def test_every_name_in_the_example_is_documented():
    assert sorted(set(NAME.findall(EXAMPLE)) - set(NAME.findall(CONFIG))) == []


def test_readme_does_not_call_the_example_complete_unless_it_is():
    claims_complete = "every option is listed in `local.example/santa.env.example`" in README
    missing = set(NAME.findall(CONFIG)) - set(NAME.findall(EXAMPLE))
    assert not (claims_complete and missing), sorted(missing)


def test_example_points_at_the_complete_list():
    header = "\n".join(EXAMPLE.splitlines()[:4])
    assert "docs/configuration.md" in header
