"""README, SECURITY.md and docs/configuration.md describe the PIN rate limit as the code enforces it.

The per-device share is keyed by network address (santa/web/access.py `_recent_by_device`), so someone using several
addresses can still fill the shared limit for a while and a family member's right PIN then waits (CHANGELOG, VULN-003
follow-up). The docs must not promise that one device can never lock the others out or that a family member is never
slowed down.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["README.md", "SECURITY.md", "docs/configuration.md"]
OVERCLAIMS = ("family member is not slowed down", "one device cannot")


def _flat(rel):
    return " ".join((ROOT / rel).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("rel", DOCS)
def test_no_overclaim(rel):
    text = _flat(rel)
    assert [p for p in OVERCLAIMS if p in text] == []


@pytest.mark.parametrize("rel", DOCS)
def test_the_share_is_per_address(rel):
    assert "5 from any one address" in _flat(rel)


@pytest.mark.parametrize("rel", ["README.md", "SECURITY.md"])
def test_the_remaining_limit_is_stated(rel):
    assert "several addresses can still" in _flat(rel)


def test_the_code_still_keys_the_share_by_address():
    src = (ROOT / "santa/web/access.py").read_text(encoding="utf-8")
    assert 'self._recent_by_device.get(client_host or ""' in src
