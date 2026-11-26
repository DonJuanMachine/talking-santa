"""Another website cannot submit PIN tries for a device (VulnHunter run 2: VULN-004).

Before, POST /unlock had no Origin check: any website open in a browser on the network could post wrong PINs to Santa
from that browser, so the tries counted against that device and locked it out (1, 5, then 30 minutes). The attacker
never learns the PIN; the harm is the lockout.

Now a PIN try from another site (a foreign or `null` Origin, or `Sec-Fetch-Site: cross-site`) is refused with 403
before it is counted. The PIN page's own form (same Origin) and clients that send no Origin are unchanged.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import pytest

from test_network_mode import PIN, lan_app, lan_client

SAME_SITE = {"origin": "https://testserver"}
CROSS_SITE = [{"origin": "https://evil.example"}, {"origin": "null"}, {"sec-fetch-site": "cross-site"},
              {"origin": "http://[", "sec-fetch-site": "same-origin"}]


@pytest.fixture
def lan(monkeypatch, tmp_path):
    return lan_client(lan_app(monkeypatch, tmp_path))


@pytest.mark.parametrize("headers", CROSS_SITE)
def test_pin_tries_from_another_site_are_refused_and_not_counted(lan, headers):
    for _ in range(10):
        r = lan.post("/unlock", data={"pin": "000000"}, headers=headers, follow_redirects=False)
        assert r.status_code == 403
    r = lan.post("/unlock", data={"pin": PIN}, headers=SAME_SITE, follow_redirects=False)
    assert r.status_code == 303                       # the device is not locked out and the limit is not used up


def test_a_right_pin_from_another_site_does_not_unlock(lan):
    r = lan.post("/unlock", data={"pin": PIN}, headers={"origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_the_pin_page_lets_its_form_send_a_real_origin(lan):
    """A browser posts a form with `Origin: null` when the page's Referrer-Policy is no-referrer (Fetch standard), and
    that is refused above, so the PIN could never be entered from an iPad. Same-origin keeps the real Origin."""
    r = lan.get("/")
    assert "/unlock" in r.text
    assert r.headers["referrer-policy"] == "same-origin"


@pytest.mark.parametrize("headers", [SAME_SITE, {}, {**SAME_SITE, "sec-fetch-site": "same-origin"}])
def test_the_pin_page_form_and_clients_without_origin_still_work(lan, headers):
    assert lan.post("/unlock", data={"pin": "000000"}, headers=headers).status_code == 401
    r = lan.post("/unlock", data={"pin": PIN}, headers=headers, follow_redirects=False)
    assert r.status_code == 303
