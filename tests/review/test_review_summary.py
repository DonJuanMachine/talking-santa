"""The 2026-11-19 VulnHunter review is summarised the same way in README and SECURITY.md, and every accepted
finding in CHANGELOG "Known open items" says why it is accepted (SECURITY.md promises "the reason each is accepted")."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXED = "the medium, 6 of the lows and 1 of the unproven ones are fixed"
FOUND = "1 medium and 16 low issues, plus 4 it could not prove"
REASONS = ("By design", "Accepted", "Only a page that has the PIN", "Not proven", "no attack shown")


def _flat(rel):
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split()).lower()


@pytest.mark.parametrize("rel", ["README.md", "SECURITY.md"])
def test_readme_and_security_say_what_was_found_and_fixed(rel):
    text = _flat(rel)
    assert FOUND in text and FIXED in text


def _accepted_bullets():
    lines = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("- VulnHunter scan 2026-11-19, the findings that are accepted"))
    block = []
    for l in lines[start + 1:]:
        if l.startswith("- ") or l.startswith("#"):
            break
        block.append(l)
    bullets, cur = [], []
    for l in block:
        if not cur and not l.startswith("  - "):
            continue                                 # the heading's wrapped second line
        if l.startswith("  - ") and cur:
            bullets.append(" ".join(cur))
            cur = []
        cur.append(l.strip())
    if cur:
        bullets.append(" ".join(cur))
    return bullets


def test_there_are_accepted_findings():
    assert len(_accepted_bullets()) >= 5


@pytest.mark.parametrize("i", range(5))
def test_each_accepted_finding_gives_a_reason(i):
    b = _accepted_bullets()[i]
    assert any(r in b for r in REASONS), b
