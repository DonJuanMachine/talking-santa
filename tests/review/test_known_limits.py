"""README "Known limits" names the exceptions that CHANGELOG "Known open items" lists for protections the README
states elsewhere: the Forget-last timing, the 4-page cap that a burst of connections can pass (VULN-005), and the
unthrottled log lines (VULN-001/010/011). The README sentences that state those protections point at Known limits."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _flat(s: str) -> str:
    return " ".join(s.split())


LIMITS = _flat(README.split("## Known limits", 1)[1].split("\n## ", 1)[0])


@pytest.mark.parametrize("phrase", [
    "Forget last pressed while Santa is still",     # the timing case removes the turn before
    "more than 4 call pages",                        # VULN-005
    "unthrottled",                                   # VULN-001/010/011
])
def test_known_limits_names_the_exception(phrase):
    assert phrase in LIMITS


def _sentence_with(text: str) -> str:
    flat = _flat(README)
    i = flat.index(text)
    end = flat.find(". ", i)
    return flat[i:end if end != -1 else None]


@pytest.mark.parametrize("claim", ["At most 4 Santa pages", "request-flooding denial of service"])
def test_the_claim_points_at_known_limits(claim):
    assert "(#known-limits)" in _sentence_with(claim), _sentence_with(claim)
