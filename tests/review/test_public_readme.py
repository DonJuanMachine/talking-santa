"""What the public README and issue forms must say before the repo goes public (pass 11, Stage E).

Each claim about the filter's measured behaviour must match the measurement recorded in CHANGELOG.md.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CHANGELOG = " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split())   # line wraps ignored
BASIS = ("182 short conversations", "ai/gemma4:e4b", "persona v1")


def _intro() -> str:
    return " ".join(README.split("## What you need")[0].split())   # the part a parent reads first, wraps ignored


def test_readme_says_it_is_a_hobby_project_for_supervising_adults():
    intro = _intro()
    assert "hobby project" in intro
    assert "adult" in intro and "supervis" in intro


def test_readme_says_the_filter_is_a_pattern_filter_with_recorded_gaps():
    intro = _intro()
    assert "word-pattern filter" in intro and "not" in intro and "exhaustive" in intro
    assert "Accepted gaps" in intro


def test_readme_states_the_measurement_basis_exactly_as_the_changelog():
    intro = _intro()
    for part in BASIS:
        assert part in intro, part
        assert part in CHANGELOG, part
    assert "0 promise-like sentences" in intro and "0 promise-like sentences" in CHANGELOG


def test_blank_issues_are_off_so_every_issue_shows_the_privacy_warning():
    cfg = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")
    assert "blank_issues_enabled: false" in cfg
