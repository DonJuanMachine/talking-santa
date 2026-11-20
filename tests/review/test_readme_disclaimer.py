"""The README's "Is this OK for my kids?" section opens with the use-at-your-own-risk disclaimer, before any bullet, so a
parent reads it first: the parent tests Santa's outputs, the software is provided as is, and the author is not liable
(full terms in LICENSE)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
HEAD = "## Is this OK for my kids?\n"
SECTION = README.split(HEAD, 1)[1].split("\n## ", 1)[0]
LEAD = " ".join(SECTION.split("\n- ", 1)[0].split())   # the text before the first bullet, wraps ignored


def test_the_parent_tests_the_outputs():
    assert "You are responsible for testing Santa's outputs to decide if this is appropriate for you." in LEAD


def test_as_is_and_no_liability_with_a_link_to_the_license():
    assert '"as is"' in LEAD and "without warranty" in LEAD and "not liable" in LEAD and "(LICENSE)" in LEAD


def test_the_disclaimer_comes_before_what_you_need():
    assert README.index(HEAD) < README.index("## What you need")
