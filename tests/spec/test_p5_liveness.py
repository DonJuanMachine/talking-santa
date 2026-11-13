"""P5-2: a liveness signal for a call. During a call the server sends {"type": "tick"} every settings.tick_s; never
while idle and never to a page turned away as busy. The page (santa/web/static/liveness.js, wired in app.js) treats
LOST_MS without any message during a call as a dead connection. Fake STT/TTS/VAD/model, no browser, no network."""
import _support  # noqa: F401  (temp profiles; must come first)

import asyncio
import copy
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _support import FakeClient
from santa.web.brain_adapter import SantaBrain
from santa.web.server import create_app
from santa.web.session import State
from santa.web.settings import Settings
from test_network_mode import messages, read_until
from test_stage_h import PROFILES, FakeSTT, FakeTTS, FakeVAD, fast_settings, make, start_call, wait_state

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "santa" / "web" / "static"


def _settings(tick_s):
    s = fast_settings(allowed_hosts=("127.0.0.1", "localhost", "::1", "testserver"))
    s.tick_s = tick_s
    return s


def _app(tick_s):
    brain = SantaBrain(client=FakeClient(), profiles=copy.deepcopy(PROFILES))
    return create_app(_settings(tick_s), brain=brain, stt=FakeSTT(), tts=FakeTTS(), vad_factory=FakeVAD)


def _state_now(ws):
    """(message types up to and including the next state message, that state), asked for with hello."""
    ws.send_json({"type": "hello"})
    out = []
    for m in messages(ws):
        out.append(m["type"])
        if m["type"] == "state":
            return out, m["state"]


def _types_until_state(ws):
    return _state_now(ws)[0]


def _poll(ws, seconds, step=0.04):
    """[(time received, type)] for about `seconds`. The test client's receive() never times out, so ask for a state
    message every `step` and read up to it: a missing tick fails the test instead of hanging it."""
    out, end = [], time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(step)
        out += [(time.monotonic(), t) for t in _types_until_state(ws)]
    return out


# ------------------------------------------------------------------------------------------------ server, session
def test_ticks_flow_only_while_a_call_is_active():
    async def go():
        sess, b, *_ = make(settings=_settings(0.1))
        await asyncio.sleep(0.35)
        idle = b.types().count("tick")
        await start_call(sess)
        await asyncio.sleep(0.6)
        await sess.hangup()
        await wait_state(sess, State.IDLE)
        i_idle = len(b.msgs)
        await asyncio.sleep(0.35)
        times = [t for t, m in b.msgs if m["type"] == "tick"]
        after = [m["type"] for _, m in b.msgs[i_idle:]]
        return idle, times, after

    idle, times, after = asyncio.run(go())
    gaps = [b - a for a, b in zip(times, times[1:])]
    print(f"\nticks: idle {idle}, during call {len(times)}, gaps {[round(g, 3) for g in gaps]}")
    assert idle == 0
    assert len(times) >= 5
    assert 0.07 < statistics.median(gaps) < 0.15
    assert "tick" not in after                           # nothing once the call is back to IDLE


# ------------------------------------------------------------------------------------------------ server, websocket
def test_websocket_gets_ticks_at_the_interval_during_a_call_and_none_while_idle():
    with TestClient(_app(0.2)) as c, c.websocket_connect("/ws") as ws:
        assert read_until(ws, "state")["state"] == "IDLE"
        time.sleep(0.7)
        assert "tick" not in _types_until_state(ws)       # idle: anything sent meanwhile would be queued before this
        ws.send_json({"type": "call"})
        ticks = [t for t, kind in _poll(ws, 1.3) if kind == "tick"]
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        print(f"\nwebsocket ticks during 1.3 s of call: {len(ticks)}, gaps {[round(g, 3) for g in gaps]}")
        assert len(ticks) >= 5
        assert 0.15 < statistics.median(gaps) < 0.3 and all(g < 0.4 for g in gaps)
        ws.send_json({"type": "hangup"})
        for _ in range(150):                              # the goodbye plays, then IDLE
            if _state_now(ws)[1] == "IDLE":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("the call never went back to IDLE")
        time.sleep(0.7)
        assert "tick" not in _types_until_state(ws)       # idle again after Hang up


def test_a_page_turned_away_as_busy_gets_no_ticks():
    with TestClient(_app(0.2)) as c, c.websocket_connect("/ws") as a, c.websocket_connect("/ws") as b:
        read_until(a, "state")
        read_until(b, "state")
        a.send_json({"type": "call"})
        assert "tick" in [kind for _, kind in _poll(a, 0.6)]   # a is on a call and ticking
        b.send_json({"type": "call"})
        assert read_until(b, "busy")
        time.sleep(0.7)
        assert "tick" not in _types_until_state(b)


def test_tick_interval_is_a_setting_and_leaves_the_page_room_for_two_missed_ticks():
    lost_ms = int(re.search(r"LOST_MS:\s*(\d+)", (STATIC / "liveness.js").read_text()).group(1))
    tick_s = Settings().tick_s
    assert 2.0 <= tick_s <= 3.0
    assert 2 * tick_s < lost_ms / 1000


# ------------------------------------------------------------------------------------------------ page
def test_call_page_loads_the_watchdog_and_feeds_it_every_message():
    html = (STATIC / "index.html").read_text()
    assert html.index('src="/static/liveness.js"') < html.index('src="/static/app.js"')
    js = (STATIC / "app.js").read_text()
    onmessage = re.search(r"ws\.onmessage = \(ev\) => \{(.*?)\};", js, re.S)
    assert onmessage and "watchdog.seen()" in onmessage.group(1)   # every message, text or audio, counts
    assert '"Lost connection to Santa"' in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_page_watchdog_with_fake_timers():
    r = subprocess.run(["node", "--test", str(ROOT / "tests" / "spec" / "js" / "liveness.test.cjs")],
                       capture_output=True, text=True, timeout=60)
    print(r.stdout[-1500:], r.stderr[-1500:])
    assert r.returncode == 0
