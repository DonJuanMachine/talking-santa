"""One device cannot stop the family from entering the PIN (VulnHunter run 2: VULN-003, Medium).

Before, every request from a device without the PIN (the PIN page, any other path, HEAD, a WebSocket that is closed
with 4401) used up one shared budget of 10 a minute. One device on the network could send 10 cheap requests a minute
and every device then got "Too many tries" with the right PIN.

Now only PIN tries (POST /unlock) count, a device that is locked out is not counted again, and one device can use at
most 5 of the shared 10 a minute. The shared limit still holds a guesser that rotates through many addresses.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import pytest
from starlette.websockets import WebSocketDisconnect

from santa.web.access import Gate
from test_network_mode import PIN, WSS, lan_app, lan_client
from test_stage_h import fast_settings

ATTACKER, PARENT, OTHER = ("10.0.0.66", 40000), ("10.0.0.7", 40001), ("10.0.0.8", 40002)


def huge_body(c):
    """A PIN try that is refused before it is read (413), so it never counts toward the device's lockout."""
    return c.post("/unlock", content=b"pin=" + b"1" * 5000,
                  headers={"content-type": "application/x-www-form-urlencoded"}).status_code


@pytest.fixture
def app(monkeypatch, tmp_path):
    return lan_app(monkeypatch, tmp_path)


def device(app, peer):
    """A LAN device at `peer`. Not entered as a context manager: the PIN gate needs no engines, and entering the same
    app twice would run its lifespan (model load, worker shutdown) twice."""
    return lan_client(app, client=peer)


def parent_unlocks(app) -> int:
    return device(app, PARENT).post("/unlock", data={"pin": PIN}, follow_redirects=False).status_code


def test_the_pin_page_and_other_paths_never_use_up_the_limit(app):
    bad = device(app, ATTACKER)
    assert {bad.get("/").status_code for _ in range(30)} == {200}
    assert {bad.get("/static/app.js").status_code for _ in range(30)} == {401}
    assert {bad.head("/").status_code for _ in range(30)} != {429}
    assert parent_unlocks(app) == 303


def test_locked_websockets_never_use_up_the_limit(app):
    bad = device(app, ATTACKER)
    for _ in range(20):
        with bad.websocket_connect(WSS) as ws:
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
        assert e.value.code == 4401
    assert parent_unlocks(app) == 303


def test_one_device_gets_at_most_5_tries_a_minute_and_the_parent_still_gets_in(app):
    bad = device(app, ATTACKER)
    codes = [huge_body(bad) for _ in range(20)]
    assert codes[:5] == [413] * 5 and set(codes[5:]) == {429}
    assert parent_unlocks(app) == 303


def test_a_locked_out_device_is_not_counted_again(app):
    bad = device(app, ATTACKER)
    codes = [bad.post("/unlock", data={"pin": "000000"}).status_code for _ in range(5)]
    assert codes == [401] * 4 + [429]                                   # the 5th wrong PIN starts its lockout
    for _ in range(20):
        r = bad.post("/unlock", data={"pin": PIN})
        assert r.status_code == 429 and "Wait" in r.text           # its own lockout, not the shared limit
    other = device(app, OTHER)
    for _ in range(4):
        assert other.post("/unlock", data={"pin": "000000"}).status_code == 401
    assert parent_unlocks(app) == 303                                   # 5 + 4 counted, 1 left


def test_many_devices_together_are_still_held_to_the_shared_limit():
    now = [0.0]
    g = Gate(fast_settings(host="0.0.0.0", pin=PIN, gate_limit_per_min=10), clock=lambda: now[0])
    results = [g.admit(f"10.0.0.{n}") for n in (1, 2, 3) for _ in range(5)]
    assert results.count(True) == 10 and results[10:] == [False] * 5
    now[0] = 60.0
    assert g.admit("10.0.0.3")                                          # the minute has passed


def test_one_device_share_resets_after_a_minute():
    now = [0.0]
    g = Gate(fast_settings(host="0.0.0.0", pin=PIN, gate_limit_per_min=10), clock=lambda: now[0])
    assert [g.admit("10.0.0.1") for _ in range(6)] == [True] * 5 + [False]
    assert g.admit("10.0.0.2")                                          # another device still has room
    now[0] = 60.0
    assert g.admit("10.0.0.1")


def test_a_too_large_pin_try_counts_toward_the_lockout_so_two_addresses_cannot_block_forever(app):
    """Fix-verify follow-up: a too-large body was answered 413 before the PIN check, so it used up the shared limit but
    never counted toward that address's lockout. Two addresses could send 5 a minute each and keep the parent out
    forever. Now it counts as a wrong try: each address is locked out (1, then 5 minutes) and stops being counted."""
    now = [1000.0]
    app.state.gate.clock = lambda: now[0]
    attackers = [device(app, (ip, 40000)) for ip in ("fe80::a", "fe80::b")]
    results = []
    for minute in range(3):
        for bad in attackers:
            for _ in range(5):
                huge_body(bad)
        results.append(parent_unlocks(app))
        now[0] += 61
    assert results[-1] == 303                       # both addresses are locked out for 5 minutes: the parent gets in
    for bad in attackers:
        r = bad.post("/unlock", data={"pin": PIN})
        assert r.status_code == 429 and "Wait" in r.text
