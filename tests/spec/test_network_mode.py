"""Access rules: Host allowlist (DNS rebinding), PIN gate with escalating lockouts, rate limit for devices without
the PIN, /status kept to this Mac, WebSocket origin check, one call at a time in network mode.

Runs the real FastAPI app with the fake STT/TTS/VAD from the Stage H tests (no models, no model server).

The network-mode app (`lan`, lan_app) is built by santa.web.__main__.main() itself, with uvicorn.run replaced by a
recorder (tests/spec/_startup.py), so it passes the same start-up guards as a real `--network` start: a PIN of at
least 6 characters, both certificate files, 0.0.0.0, TLS files and proxy_headers=False handed to uvicorn. The
TestClient then talks to that app over plain HTTP (TLS is uvicorn's layer, which the recorder checks). The default-
mode app (`local`, app_for) and the Gate unit tests still build directly: main() adds nothing to default mode but
the 127.0.0.1 bind, which test_startup_guards.py checks, and the TestClient's Host ("testserver") has to be allowed
by hand there, which main() never does.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import copy
import json
from dataclasses import fields

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from _startup import GUARDED, cert_files, launch
from _support import FakeClient
from santa.web.access import Gate, host_name, origin_ok
from santa.web.brain_adapter import SantaBrain
from santa.web.server import create_app
from santa.web.settings import Settings
from test_stage_h import PROFILES, FakeSTT, FakeTTS, FakeVAD, fast_settings

PIN = "432198"                      # main() refuses --network with a PIN shorter than 6 characters


def app_for(alerter=None, **kw):
    kw.setdefault("allowed_hosts", ("127.0.0.1", "localhost", "::1", "testserver"))   # TestClient sends Host: testserver
    s = fast_settings(**kw)
    brain = SantaBrain(client=FakeClient(), profiles=copy.deepcopy(PROFILES))
    return create_app(s, alerter=alerter, brain=brain, stt=FakeSTT(), tts=FakeTTS(), vad_factory=FakeVAD)


@pytest.fixture
def local():
    with TestClient(app_for()) as c:
        yield c


def lan_app(monkeypatch, tmp_path, pin=PIN):
    """The app a real `python -m santa.web --network` start would serve, with the Stage H fakes and fast timings.
    "testserver" plays the Mac's LAN name (the name devices use), so the TestClient's Host header is allowed."""
    fast, default = fast_settings(), Settings()
    timings = {f.name: getattr(fast, f.name) for f in fields(Settings)
               if f.name not in GUARDED and getattr(fast, f.name) != getattr(default, f.name)}
    engines = dict(brain=SantaBrain(client=FakeClient(), profiles=copy.deepcopy(PROFILES)), stt=FakeSTT(),
                   tts=FakeTTS(), vad_factory=FakeVAD)
    cert, key = cert_files(tmp_path)
    (app, kw), = launch(monkeypatch, ["--network", "--cert", str(cert), "--key", str(key)], pin=pin,
                        lan=("testserver",), engines=engines, overrides=timings)
    assert kw["host"] == "0.0.0.0" and kw["ssl_certfile"] == str(cert) and kw["proxy_headers"] is False
    return app


WSS = "wss://testserver/ws"     # the page's socket on an https page; a relative "/ws" would go out as ws:// (no cookie)


def lan_client(app, **kw):
    """A LAN device. https, as on a real --network start: the unlock cookie is Secure there (cert_file is set)."""
    return TestClient(app, base_url="https://testserver", **kw)


@pytest.fixture
def lan(monkeypatch, tmp_path):
    with lan_client(lan_app(monkeypatch, tmp_path)) as c:   # the test client is not loopback: a LAN device
        yield c


def messages(ws, limit=500):
    """JSON messages only; Santa's audio arrives as binary frames in between."""
    for _ in range(limit):
        m = ws.receive()
        if m.get("type") == "websocket.close":
            raise AssertionError("socket closed")
        if m.get("text") is not None:
            yield json.loads(m["text"])


def read_until(ws, kind):
    for m in messages(ws):
        if m["type"] == kind:
            return m
    raise AssertionError(f"no {kind} message")


def read_state(ws, want_idle: bool):
    for m in messages(ws):
        if m["type"] == "state" and (m["state"] == "IDLE") == want_idle:
            return m
    raise AssertionError("state not reached")


# ------------------------------------------------------------------------------------------------- default mode
def test_default_mode_is_unchanged_no_pin_and_status_works(local):
    assert 'id="big"' in local.get("/").text
    assert local.get("/static/app.js").status_code == 200
    assert local.get("/status").status_code == 200
    with local.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello"})
        assert ws.receive_json()["type"] == "state"


def test_websocket_from_another_website_is_refused(local):
    with pytest.raises(WebSocketDisconnect):
        with local.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    with local.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "state"


# ------------------------------------------------------------------------------------------------- network mode
def test_locked_device_sees_only_the_pin_page(lan):
    r = lan.get("/")
    assert r.status_code == 200 and 'action="/unlock"' in r.text and 'id="big"' not in r.text
    assert lan.get("/static/app.js").status_code == 401
    assert lan.get("/santa-image").status_code == 401


def test_status_is_this_mac_only_in_network_mode(lan):
    assert lan.get("/status").status_code == 404
    lan.post("/unlock", data={"pin": PIN})
    assert lan.get("/status").status_code == 404         # even after unlocking: children's names stay on the Mac


def test_locked_websocket_is_closed_with_4401_and_no_names_are_sent(lan):
    with lan.websocket_connect(WSS) as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 4401


def test_wrong_pin_is_refused_and_right_pin_unlocks(lan):
    r = lan.post("/unlock", data={"pin": "0000"}, follow_redirects=False)
    assert r.status_code == 401 and "not right" in r.text
    r = lan.post("/unlock", data={"pin": PIN}, follow_redirects=False)
    assert r.status_code == 303
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert 'id="big"' in lan.get("/").text
    with lan.websocket_connect(WSS) as ws:
        assert ws.receive_json()["type"] == "state"


def test_too_many_wrong_pins_lock_the_device_out(lan):
    for _ in range(5):
        lan.post("/unlock", data={"pin": "0000"})
    r = lan.post("/unlock", data={"pin": PIN}, follow_redirects=False)
    assert r.status_code == 429 and "Wait" in r.text
    assert 'id="big"' not in lan.get("/").text


def test_only_one_call_at_a_time_in_network_mode(lan):
    lan.post("/unlock", data={"pin": PIN})
    with lan.websocket_connect(WSS) as a, lan.websocket_connect(WSS) as b:
        read_state(a, want_idle=True)
        read_state(b, want_idle=True)
        a.send_json({"type": "call"})
        read_state(a, want_idle=False)
        b.send_json({"type": "call"})
        assert read_until(b, "busy") == {"type": "busy"}
        a.send_json({"type": "hangup"})
        read_state(a, want_idle=True)
        b.send_json({"type": "call"})                     # free again
        read_state(b, want_idle=False)
        b.send_json({"type": "hangup"})


# ------------------------------------------------------------------------------------------------- gate rules
def test_this_mac_is_never_asked_for_the_pin():
    g = Gate(fast_settings(host="0.0.0.0", pin=PIN))
    assert g.allowed("127.0.0.1", {}) and g.allowed("::1", {})
    assert not g.allowed("192.168.1.50", {})


def test_lockout_ends_after_the_wait():
    now = [0.0]
    g = Gate(fast_settings(host="0.0.0.0", pin=PIN, pin_max_tries=3), clock=lambda: now[0])
    for _ in range(3):
        assert g.try_pin("10.0.0.5", "9999") is None
    assert g.try_pin("10.0.0.5", PIN) is None             # locked, even with the right PIN
    assert g.try_pin("10.0.0.6", PIN)                     # another device is not affected
    now[0] = 61
    assert g.try_pin("10.0.0.5", PIN)


def test_each_lockout_is_longer_and_never_resets_to_the_first():
    now = [0.0]
    g = Gate(fast_settings(host="0.0.0.0", pin=PIN, pin_max_tries=2, pin_lockouts=(60, 300, 1800)),
             clock=lambda: now[0])
    ip = "10.0.0.9"
    for expect in (60, 300, 1800, 1800):                  # 4th lockout stays at the longest
        for _ in range(2):
            g.try_pin(ip, "0000")
        assert g.locked_for(ip) == expect
        now[0] += expect
    assert g.try_pin(ip, PIN)                             # the right PIN still works after waiting
    g.try_pin(ip, "0000"); g.try_pin(ip, "0000")
    assert g.locked_for(ip) == 60                         # a correct PIN clears that device's history


def test_rate_limit_counts_all_locked_devices_together():
    now = [0.0]
    g = Gate(fast_settings(host="0.0.0.0", pin=PIN, gate_limit_per_min=10), clock=lambda: now[0])
    assert all(g.admit() for _ in range(10))
    assert not g.admit()
    now[0] = 59.9
    assert not g.admit()
    now[0] = 60.0                                          # the minute has passed
    assert g.admit()


def test_host_names_are_parsed_without_port_or_brackets():
    assert host_name("System.LOCAL:8765") == "system.local"
    assert host_name("[::1]:8765") == "::1"
    assert host_name("127.0.0.1") == "127.0.0.1"
    assert host_name(None) is None and host_name("") is None


def test_origin_must_match_host():
    assert origin_ok(None, "system.local:8765")
    assert origin_ok("https://system.local:8765", "system.local:8765")
    assert not origin_ok("https://evil.example", "system.local:8765")
    assert not origin_ok("https://system.local:9999", "system.local:8765")


# ------------------------------------------------------------------------------------------------- DNS rebinding
def test_unknown_host_is_refused_even_from_this_mac():
    """A rebinding page reaches 127.0.0.1 but its requests carry the attacker's Host."""
    with TestClient(app_for(), client=("127.0.0.1", 50000)) as c:
        evil = {"host": "evil.example:8765"}
        assert c.get("/", headers=evil).status_code == 400
        assert c.get("/status", headers=evil).status_code == 400
        assert c.get("/santa-image", headers=evil).status_code == 400
        assert c.get("/status").status_code == 200        # the real name still works
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws", headers={**evil, "origin": "http://evil.example:8765"}) as ws:
                ws.receive_json()
        with c.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
            assert ws.receive_json()["type"] == "state"


def test_default_names_do_not_include_lan_names():
    g = Gate(fast_settings())
    assert g.host_ok("127.0.0.1:8765") and g.host_ok("localhost:8765") and g.host_ok("[::1]:8765")
    assert not g.host_ok("system.local:8765") and not g.host_ok("evil.example")


def test_extra_hosts_are_added():
    g = Gate(fast_settings(extra_hosts=("santa.home",)))
    assert g.host_ok("santa.home:8765")


# ------------------------------------------------------------------------------------------------- rate limit (app)
def test_locked_devices_are_rate_limited_but_unlocked_ones_and_this_mac_are_not(lan):
    assert lan.post("/unlock", data={"pin": PIN}).status_code == 200      # 1 counted request (then unlocked)
    for _ in range(15):
        assert lan.get("/").status_code == 200                           # unlocked: never counted
    other = lan_client(lan.app)                                          # a second device, no cookie
    codes = [other.get("/").status_code for _ in range(12)]
    assert codes.count(200) == 9 and codes[-1] == 429                    # 10 per minute in total, both devices
    assert other.get("/").headers.get("retry-after") == "60"
    with lan_client(lan.app, client=("127.0.0.1", 50001)) as mac:
        assert mac.get("/").status_code == 200                           # this Mac is never limited
