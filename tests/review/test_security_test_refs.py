"""SECURITY.md cites tests that exist and does not call a tested protection untested.

The "Protections" table names test files for each protection, and a sentence below it lists what has no test of its
own. tests/spec/test_startup_guards.py covers ignoring proxy headers and the 6-character PIN rule, so those must be
cited, not listed as untested.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
GUARDS = (ROOT / "tests" / "spec" / "test_startup_guards.py").read_text(encoding="utf-8")


def _untested_sentence() -> str:
    flat = " ".join(SECURITY.split())
    m = re.search(r"[^.]*\bdo(?:es)? not have a test of (?:their|its) own\.", flat)
    assert m, "the sentence about untested protections is gone (update this test)"
    return m.group(0)


def test_every_cited_test_file_exists():
    cited = set(re.findall(r"`(tests/[^`]+\.py)`", SECURITY))
    assert cited and sorted(c for c in cited if not (ROOT / c).is_file()) == []


def test_the_startup_guards_still_cover_proxy_headers_and_the_pin_rule():
    assert 'kw["proxy_headers"] is False' in GUARDS
    assert "def test_network_without_a_6_character_pin_exits_non_zero" in GUARDS


def test_tested_protections_are_not_called_untested():
    s = _untested_sentence().lower()
    assert "proxy" not in s and "pin" not in s, s


def test_the_spoofed_address_row_cites_the_startup_guards():
    row = next(line for line in SECURITY.splitlines() if line.startswith("| Spoofed client address"))
    assert "tests/spec/test_startup_guards.py" in row
