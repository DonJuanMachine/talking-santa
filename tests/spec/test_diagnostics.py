"""Connection diagnostics: when a call page says "Lost connection", the server log says why. Numbers and state names
only (no speech, no names); the page cannot write its own text into the log. Fake STT/TTS/VAD/model, no browser."""
import _support  # noqa: F401  (temp profiles; must come first)

import asyncio
import copy
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _support import FakeClient
from santa.web import session as session_mod
from santa.web.brain_adapter import SantaBrain
from santa.web.server import create_app
from test_network_mode import read_until
from test_stage_h import PROFILES, FakeSTT, FakeTTS, FakeVAD, fast_settings, make, start_call

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "santa" / "web" / "static"


def _app():
    s = fast_settings(allowed_hosts=("127.0.0.1", "localhost", "::1", "testserver"))
    brain = SantaBrain(client=FakeClient(), profiles=copy.deepcopy(PROFILES))
    return create_app(s, brain=brain, stt=FakeSTT(), tts=FakeTTS(), vad_factory=FakeVAD)


def _wait_for(caplog, text, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        hits = [r for r in caplog.records if text in r.getMessage()]
        if hits:
            return hits
        time.sleep(0.02)
    return []


# ------------------------------------------------------------------------------------------------ connection closes
def test_a_close_during_a_call_is_a_warning_with_the_close_code_and_the_numbers(caplog):
    caplog.set_level(logging.INFO, logger="santa.web")
    with TestClient(_app()) as c:
        with c.websocket_connect("/ws") as ws:
            read_until(ws, "state")
            ws.send_json({"type": "call"})
            read_until(ws, "ring_start")
            ws.close(code=4000)                           # what the page does when its watchdog gives up
        hits = _wait_for(caplog, "connection closed during a call")
    assert hits, [r.getMessage() for r in caplog.records]
    r = hits[0]
    assert r.levelno == logging.WARNING
    msg = r.getMessage()
    print("\n" + msg)
    assert "close code 4000" in msg
    assert re.search(r"state=(RINGING|GREETING)", msg)
    for key in ("call_s=", "turns=", "page_silent_s=", "last_tick_s=", "server_up_h="):
        assert key in msg


def test_a_close_while_idle_is_not_a_warning(caplog):
    caplog.set_level(logging.INFO, logger="santa.web")
    with TestClient(_app()) as c:
        with c.websocket_connect("/ws") as ws:
            read_until(ws, "state")
        hits = _wait_for(caplog, "connection closed while idle")
    assert hits and hits[0].levelno == logging.INFO
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING and "closed" in r.getMessage()]


def test_call_start_and_end_are_logged_at_info_with_the_reason(caplog):
    caplog.set_level(logging.INFO, logger="santa.web")

    async def go():
        sess, *_ = make()
        await start_call(sess)
        await sess.hangup(reason="silence")

    asyncio.run(go())
    texts = [r.getMessage() for r in caplog.records]
    assert any(t.startswith("call started: state=RINGING") for t in texts), texts
    assert any(t.startswith("call ending (silence): ") for t in texts), texts
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ------------------------------------------------------------------------------------------------ the server side
def test_a_late_tick_is_logged_with_how_late(caplog, monkeypatch):
    monkeypatch.setattr(session_mod, "TICK_LATE_S", 0.1)
    caplog.set_level(logging.INFO, logger="santa.web")

    async def go():
        s = fast_settings()
        s.tick_s = 0.05
        sess, *_ = make(settings=s)
        await start_call(sess)
        await asyncio.sleep(0.2)
        time.sleep(0.5)                                   # block the event loop, like a long synchronous step
        await asyncio.sleep(0.2)
        await sess.close()

    asyncio.run(go())
    late = [r.getMessage() for r in caplog.records if "tick was" in r.getMessage()]
    print("\n" + "\n".join(late))
    assert late and "late" in late[0] and "state=" in late[0]
    assert float(re.search(r"was ([\d.]+) s late", late[0]).group(1)) >= 0.3


def test_ticks_on_time_log_nothing(caplog):
    caplog.set_level(logging.INFO, logger="santa.web")

    async def go():
        s = fast_settings()
        s.tick_s = 0.05
        sess, *_ = make(settings=s)
        await start_call(sess)
        await asyncio.sleep(0.4)
        await sess.close()

    asyncio.run(go())
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_failed_send_is_logged_once(caplog):
    caplog.set_level(logging.INFO, logger="santa.web")

    async def go():
        sess, *_ = make()

        async def broken(_):
            raise ConnectionResetError("gone")

        sess._send_json = broken
        sess._send_bytes = broken
        await sess.send({"type": "tick"})
        await sess.send({"type": "tick"})
        await sess.send_bytes(b"x")
        return sess

    sess = asyncio.run(go())
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == 1 and sess.closed
    assert "ConnectionResetError" in warned[0] and "sending tick" in warned[0] and "gone" not in warned[0]


def test_diag_is_numbers_and_state_names_only():
    async def go():
        sess, *_ = make()
        idle = sess.diag()
        await start_call(sess)
        sess.note_page_message()
        return idle, sess.diag()

    idle, busy = asyncio.run(go())
    print("\n" + idle + "\n" + busy)
    assert idle.startswith("state=IDLE call_s=- turns=-")
    assert busy.startswith("state=") and "call_s=" in busy and "page_silent_s=0" in busy
    for name in PROFILES:
        assert name not in busy


# ------------------------------------------------------------------------------------------------ the page's report
def test_the_pages_report_is_logged_as_numbers_and_the_page_cannot_write_its_own_text(caplog):
    caplog.set_level(logging.INFO, logger="santa.web")

    async def go():
        sess, *_ = make()
        await sess.handle({"type": "client_lost", "silent_ms": 6012.34, "check_gap_ms": 7400, "buffered": 0,
                           "visible": "hidden", "state": "LISTENING"})
        await sess.handle({"type": "client_lost", "silent_ms": "evil\nFAKE LOG LINE", "check_gap_ms": float("nan"),
                           "buffered": -5, "visible": "evil\nvisible", "state": {"a": 1}})
        await sess.handle({"type": "client_lost", "silent_ms": True, "check_gap_ms": 10**30})

    asyncio.run(go())
    texts = [r.getMessage() for r in caplog.records if "gave up" in r.getMessage()]
    assert len(texts) == 3
    print("\n" + "\n".join(texts))
    assert "nothing received for 6012.3 ms" in texts[0] and "up to 7400 ms apart" in texts[0]
    assert "tab hidden" in texts[0] and "page state LISTENING" in texts[0]
    for t in texts[1:]:
        assert "\n" not in t and "evil" not in t and "FAKE" not in t
        assert "tab ?" in t and "page state ?" in t and "nothing received for -1 ms" in t


def test_a_client_lost_message_over_the_websocket_reaches_the_log(caplog):
    caplog.set_level(logging.INFO, logger="santa.web")
    with TestClient(_app()) as c, c.websocket_connect("/ws") as ws:
        read_until(ws, "state")
        ws.send_json({"type": "client_lost", "silent_ms": 6100, "check_gap_ms": 6500, "buffered": 0,
                      "visible": "visible", "state": "THINKING"})
        hits = _wait_for(caplog, "the page gave up on the connection")
    assert hits and hits[0].levelno == logging.WARNING and "tab visible" in hits[0].getMessage()


# ------------------------------------------------------------------------------------------------ page
def test_page_closes_with_4000_and_reports_what_it_saw_after_reconnecting():
    js = (STATIC / "app.js").read_text()
    assert re.search(r"dead\.close\(4000,", js)
    assert "console.warn(" in js
    onopen = re.search(r"ws\.onopen = \(\) => \{(.*?)\n    \};", js, re.S)
    assert onopen and 'type: "client_lost"' in onopen.group(1) and "lostReport = null" in onopen.group(1)
    assert "function connectionLost(why)" in js and "...why" in js
    assert "watchdog.seen()" in re.search(r"ws\.onmessage = \(ev\) => \{(.*?)\};", js, re.S).group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_watchdog_reports_what_it_saw_with_fake_timers():
    r = subprocess.run(["node", "--test", str(ROOT / "tests" / "spec" / "js" / "liveness.test.cjs")],
                       capture_output=True, text=True, timeout=60)
    print(r.stdout[-1500:], r.stderr[-1500:])
    assert r.returncode == 0
