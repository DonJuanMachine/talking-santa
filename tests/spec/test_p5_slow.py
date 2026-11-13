"""P5-1 follow-up (notes/review/plans/p5-slow-state-plan.md, Option B): when Santa's brain is slow to start an answer,
the page is told ({"type": "slow"}, once per turn, after settings.slow_s) and Santa says one canned hold line
("hold", at most once per settings.hold_every_s per call). A turn answered before slow_s is unchanged (I9).

The model runner is a fake that accepts the streamed request and blocks on an event until its own (scaled) timeout,
then raises, as httpx would; the brain then yields FALLBACK. Fake STT/TTS/VAD, no browser, no network, no Docker.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import asyncio
import copy
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _support import FakeClient
from santa import config, spec, speech
from santa.spec import FALLBACK
from santa.web import canned, safe
from santa.web.brain_adapter import SantaBrain
from santa.web.server import create_app
from santa.web.session import State
from santa.web.settings import Settings
from test_stage_h import PROFILES, FakeSTT, FakeTTS, FakeVAD, fast_settings, make, say, start_call, until, wait_state

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "santa" / "web" / "static"
HOLD = "Hmm, let me think about that."
SLOW_S = 0.2            # scaled SANTA_SLOW_S (10 s in the app)
R = 0.6                 # scaled SANTA_TIMEOUT (15 s in the app)
W = 0.6                 # scaled SANTA_WARMUP_TIMEOUT (90 s in the app)
REPLY = "Ho ho! Snow is lovely and white. Do you like to build a snowman?"


class StuckRunner(FakeClient):
    """The streamed request blocks on `answer` until config.REQUEST_TIMEOUT, then raises (the brain answers with
    FALLBACK). Set `answer` and it streams its reply. Warm-ups answer at once unless `warm_hangs` is set."""

    def __init__(self, warm_hangs=False, **kw):
        super().__init__(**kw)
        self.answer = threading.Event()
        self.warm_hangs = warm_hangs

    def with_options(self, **opts):
        def create(**kw):
            self.warm_calls.append(kw)
            if self.warm_hangs and not self.answer.wait(opts["timeout"].read):
                raise TimeoutError("warm-up timed out")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="h"))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def _create(self, **kw):
        if kw.get("stream") and not self.answer.wait(config.REQUEST_TIMEOUT):
            self.calls.append(kw)
            raise TimeoutError("request timed out")
        return super()._create(**kw)


@pytest.fixture
def scaled(monkeypatch):
    monkeypatch.setattr(config, "REQUEST_TIMEOUT", R)
    monkeypatch.setattr(config, "WARMUP_TIMEOUT", W)


def _s(**kw):
    return fast_settings(**{"slow_s": SLOW_S, "hold_every_s": 60.0, **kw})


def _after(b, i):
    """(time, msg) sent from index i on."""
    return b.msgs[i:]


def _turn_start(b, i=0):
    """Index and time of the first THINKING state message from index i on (the turn's start)."""
    for j, (t, m) in enumerate(b.msgs[i:], i):
        if m["type"] == "state" and m["state"] == "THINKING":
            return j, t
    raise AssertionError("no THINKING state")


def _slows(b, i=0):
    return [(t, m) for t, m in b.msgs[i:] if m["type"] == "slow"]


def _reply_audio_starts(b, i=0):
    """Times of audio_start messages for replies (not canned lines) from index i on."""
    return [t for t, m in b.msgs[i:] if m["type"] == "audio_start" and "canned" not in m]


def _states_from(b, i):
    return [m["state"] for _, m in b.msgs[i:] if m["type"] == "state"]


async def _hang_up(sess, client=None):
    if client is not None:
        client.answer.set()                              # release the brain thread
    await sess.hangup()
    await wait_state(sess, State.IDLE)


# ------------------------------------------------------------------------------------------------ 1) I9 guard
def test_a_turn_answered_before_slow_s_sends_no_slow_message_and_plays_no_hold_line(scaled):
    async def go():
        client = StuckRunner(replies=[REPLY])
        sess, b, brain, stt, tts = make(settings=_s(slow_s=0.4), client=client)
        await start_call(sess)
        n0 = len(tts.lines)
        i0 = len(b.msgs)
        await say(sess, 1.0)
        await wait_state(sess, State.THINKING)
        threading.Timer(0.15, client.answer.set).start()  # the answer starts at 0.15 s: slow but under slow_s
        await until(lambda: sess.counters["turns"] == 1, timeout=5)
        await wait_state(sess, State.LISTENING)
        await asyncio.sleep(0.5)                         # past slow_s: nothing late either
        out = (b.types(), tts.lines[n0:], _states_from(b, i0), dict(sess.counters))
        await _hang_up(sess)
        return out

    types, lines, states, counters = asyncio.run(go())
    print(f"\nhealthy turn: lines {len(lines)}, states {states}, slow messages {types.count('slow')}")
    assert "slow" not in types
    assert HOLD not in lines and FALLBACK not in lines and lines
    assert states == ["THINKING", "SPEAKING", "LISTENING"]
    assert counters["slow_turns"] == 0


def test_a_healthy_call_end_to_end_sends_no_slow_message():
    async def go():
        sess, b, brain, stt, tts = make(settings=_s(), client=FakeClient(replies=[REPLY]))
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: sess.counters["turns"] == 1)
        await wait_state(sess, State.LISTENING)
        await asyncio.sleep(SLOW_S + 0.2)
        out = (b.types(), list(tts.lines), sess.counters["slow_turns"])
        await _hang_up(sess)
        return out

    types, lines, slow_turns = asyncio.run(go())
    assert "slow" not in types and HOLD not in lines and slow_turns == 0


# ------------------------------------------------------------------------------------------------ 2) one slow message
def test_a_hung_turn_sends_exactly_one_slow_message_after_slow_s_while_thinking(scaled):
    async def go():
        client = StuckRunner()
        sess, b, brain, stt, tts = make(settings=_s(), client=client)
        await start_call(sess)
        i0 = len(b.msgs)
        await say(sess, 1.0)
        await until(lambda: FALLBACK in tts.lines, timeout=5)
        await wait_state(sess, State.LISTENING)
        j, t_turn = _turn_start(b, i0)
        slows = _slows(b, i0)
        # the state the page was in when each slow message arrived
        in_state = []
        for ts, _ in slows:
            last = [m["state"] for t, m in b.msgs if m["type"] == "state" and t <= ts]
            in_state.append(last[-1])
        out = ([(ts - t_turn, m) for ts, m in slows], in_state, sess.counters["slow_turns"])
        await _hang_up(sess, client)
        return out

    slows, in_state, slow_turns = asyncio.run(go())
    print(f"\nslow messages (s from turn start): {[(round(t, 3), m) for t, m in slows]}")
    assert len(slows) == 1
    t, msg = slows[0]
    assert msg == {"type": "slow"}
    assert SLOW_S - 0.02 <= t < SLOW_S + 0.2
    assert in_state == ["THINKING"]
    assert slow_turns == 1


# ------------------------------------------------------------------------------------------------ 3) hold, then FALLBACK
def test_a_hung_turn_plays_the_hold_line_once_then_fallback(scaled):
    async def go():
        client = StuckRunner()
        sess, b, brain, stt, tts = make(settings=_s(), client=client)
        await start_call(sess)
        b.play_s = 0.1                                   # the hold line takes a little while to play
        n0, i0 = len(tts.lines), len(b.msgs)
        await say(sess, 1.0)
        await until(lambda: FALLBACK in tts.lines, timeout=5)
        await wait_state(sess, State.LISTENING)
        j, t_turn = _turn_start(b, i0)
        hold_start = [t for t, m in b.msgs[j:] if m["type"] == "audio_start" and m.get("canned") == "hold"]
        thinking = [t for t, m in b.msgs[j + 1:] if m["type"] == "state" and m["state"] == "THINKING"]
        slow = [t for t, _ in _slows(b, j)]
        fb = _reply_audio_starts(b, j)
        timeline = {"slow": slow[0] - t_turn, "hold_start": hold_start[0] - t_turn,
                    "hold_end": thinking[0] - t_turn, "fallback": fb[0] - t_turn}
        history = [m["content"] for m in brain.santa.history]
        out = (tts.lines[n0:], _states_from(b, j), timeline, history, len(hold_start))
        await _hang_up(sess, client)
        return out

    lines, states, timeline, history, holds = asyncio.run(go())
    print("\nhung turn timeline (ms from turn start): " +
          ", ".join(f"{k} {v * 1000:.0f}" for k, v in timeline.items()) + f" (slow_s {SLOW_S}, R {R}, play 0.1)")
    assert lines == [HOLD, FALLBACK]
    assert holds == 1
    assert states == ["THINKING", "SPEAKING", "THINKING", "SPEAKING", "LISTENING"]
    assert SLOW_S - 0.02 <= timeline["hold_start"] < SLOW_S + 0.15
    assert timeline["hold_start"] < timeline["hold_end"] <= timeline["slow"] < timeline["fallback"]
    assert not any(HOLD in str(c) for c in history)      # the brain's history does not record the filler


# ------------------------------------------------------------------------------------------------ 4) answer during hold
def _lines_of_a_healthy_turn():
    async def go():
        sess, b, brain, stt, tts = make(settings=_s(), client=FakeClient(replies=[REPLY]))
        await start_call(sess)
        n0 = len(tts.lines)
        await say(sess, 1.0)
        await until(lambda: sess.counters["turns"] == 1)
        out = tts.lines[n0:]
        await _hang_up(sess)
        return out
    return asyncio.run(go())


def test_an_answer_arriving_during_the_hold_line_plays_right_after_it_in_order(scaled):
    healthy = _lines_of_a_healthy_turn()
    hits = safe.tripwire_hits

    async def go():
        client = StuckRunner(replies=[REPLY])
        sess, b, brain, stt, tts = make(settings=_s(), client=client)
        await start_call(sess)
        b.play_s = 0.4                                   # the hold line is still playing when the answer arrives
        n0, i0 = len(tts.lines), len(b.msgs)
        await say(sess, 1.0)
        await until(lambda: HOLD in tts.lines, timeout=5)
        t_answer = time.monotonic()
        client.answer.set()
        await until(lambda: sess.counters["turns"] == 1, timeout=5)
        j, _ = _turn_start(b, i0)
        back = [t for t, m in b.msgs[j + 1:] if m["type"] == "state" and m["state"] == "THINKING"][0]
        first = _reply_audio_starts(b, j)[0]
        out = (tts.lines[n0:], back - t_answer, first - back, _states_from(b, j))
        await _hang_up(sess)
        return out

    lines, answer_to_hold_end, gap, states = asyncio.run(go())
    print(f"\nanswer during hold: hold ended {answer_to_hold_end:.3f} s after the answer started, "
          f"reply audio {gap * 1000:.0f} ms after the hold line ended")
    assert lines[0] == HOLD
    assert lines[1:] == healthy                          # nothing lost, nothing reordered, no FALLBACK
    assert FALLBACK not in lines
    assert answer_to_hold_end > 0.2                      # the answer really arrived during the hold line
    assert gap < 0.1                                     # ...and started right after it
    assert states[:4] == ["THINKING", "SPEAKING", "THINKING", "SPEAKING"]
    assert safe.tripwire_hits == hits                    # every line passed assert_speakable (FakeTTS.synth)


# ------------------------------------------------------------------------------------------------ 5) hang up in hold
def test_hang_up_during_the_hold_line_stops_at_once_and_no_fallback_follows(scaled):
    async def go():
        client = StuckRunner()
        sess, b, brain, stt, tts = make(settings=_s(), client=client)
        await start_call(sess)
        b.play_s = 1.0
        n0 = len(tts.lines)
        await say(sess, 1.0)
        await until(lambda: HOLD in tts.lines and sess.state == State.SPEAKING, timeout=5)
        await asyncio.sleep(0.05)
        b.play_s = 0.0
        t = time.monotonic()
        await sess.hangup()
        stop = [ts for ts, m in b.msgs if m["type"] == "stop_audio" and ts >= t][0] - t
        await wait_state(sess, State.IDLE)
        await asyncio.sleep(R + 0.2)                     # past the request's timeout: the brain yields FALLBACK now
        out = (stop, tts.lines[n0:], sess.state, dict(sess.counters))
        client.answer.set()
        return out

    stop, lines, state, counters = asyncio.run(go())
    print(f"\nhang up during the hold line: stop_audio after {stop * 1000:.1f} ms; lines {lines}")
    assert stop < 0.1
    assert lines == [HOLD, canned.TEXT["goodbye"]]
    assert state == State.IDLE
    assert counters["cancelled_turns"] == 1


# ------------------------------------------------------------------------------------------------ 6) rate limit
def _two_slow_turns(hold_every_s):
    async def go():
        client = StuckRunner()
        sess, b, brain, stt, tts = make(settings=_s(hold_every_s=hold_every_s), client=client,
                                        stt=FakeSTT(["hi santa", "are you there"]))
        await start_call(sess)
        n0, i0 = len(tts.lines), len(b.msgs)
        await say(sess, 1.0)
        await until(lambda: tts.lines.count(FALLBACK) == 1, timeout=5)
        await say(sess, 1.0)
        await until(lambda: tts.lines.count(FALLBACK) == 2, timeout=5)
        await wait_state(sess, State.LISTENING)
        out = (tts.lines[n0:], len(_slows(b, i0)), sess.counters["slow_turns"])
        await _hang_up(sess, client)
        return out
    return asyncio.run(go())


def test_two_slow_turns_within_the_hold_interval_play_the_hold_line_only_on_the_first(scaled):
    lines, slows, slow_turns = _two_slow_turns(60.0)
    print(f"\ntwo slow turns: {lines}, slow messages {slows}")
    assert lines == [HOLD, FALLBACK, FALLBACK]
    assert slows == 2 and slow_turns == 2                # the page is told on every slow turn


def test_the_hold_interval_is_a_setting(scaled):
    lines, slows, _ = _two_slow_turns(0.0)
    assert lines == [HOLD, FALLBACK, HOLD, FALLBACK]
    assert slows == 2


def test_settings_defaults():
    s = Settings()
    assert s.slow_s == 10.0
    assert s.hold_every_s == 60.0
    assert config.WARMUP_TIMEOUT == 90 and config.REQUEST_TIMEOUT == 15     # no timeout changed


# ------------------------------------------------------------------------------------------------ 7) ring
def test_a_slow_ring_warm_up_sends_slow_where_ring_once_and_a_fast_one_sends_nothing(scaled):
    async def go(client):
        sess, b, brain, stt, tts = make(settings=_s(), client=client)
        await start_call(sess)                           # ring_max_s 0.3 < W: the greeting starts mid warm-up
        await asyncio.sleep(0.1)
        out = (_slows(b), [m["state"] for _, m in b.msgs if m["type"] == "state"], b.msgs,
               sess.counters["slow_turns"])
        await _hang_up(sess, client if isinstance(client, StuckRunner) else None)
        return out

    slows, states, msgs, slow_turns = asyncio.run(go(StuckRunner(warm_hangs=True)))
    print(f"\nslow ring warm-up: {[m for _, m in slows]}")
    assert [m for _, m in slows] == [{"type": "slow", "where": "ring"}]
    t_slow = slows[0][0]
    greeting = [t for t, m in msgs if m["type"] == "audio_start" and m.get("canned") == "greeting"][0]
    ring_stop = [t for t, m in msgs if m["type"] == "ring_stop"][0]
    assert ring_stop <= t_slow <= greeting               # sent as the greeting starts
    assert slow_turns == 0                               # a ring is not a turn

    slows, *_ = asyncio.run(go(FakeClient()))
    assert slows == []


# ------------------------------------------------------------------------------------------------ 8) silence watch
def test_the_silence_watch_never_fires_during_a_long_thinking(monkeypatch):
    monkeypatch.setattr(config, "REQUEST_TIMEOUT", 1.0)

    async def go():
        client = StuckRunner()
        sess, b, brain, stt, tts = make(settings=_s(silence_prompt_s=0.2), client=client)
        await start_call(sess)
        n0, i0 = len(tts.lines), len(b.msgs)
        await say(sess, 1.0)
        await until(lambda: FALLBACK in tts.lines, timeout=5)
        out = (tts.lines[n0:], _states_from(b, i0), dict(sess.counters))
        await _hang_up(sess, client)
        return out

    lines, states, counters = asyncio.run(go())
    assert lines == [HOLD, FALLBACK]                     # no "still_here" during the 1 s wait
    assert counters["silence_prompts"] == 0 and counters["silence_hangups"] == 0
    assert "HANGUP" not in states


# ------------------------------------------------------------------------------------------------ 9) the line itself
def test_the_hold_line_is_canned_checked_and_rendered_like_the_others():
    assert canned.TEXT["hold"] == HOLD
    assert safe.canned(HOLD) == HOLD
    assert speech.sanitize_ex(HOLD) == (HOLD, None) and spec.safety_reason(HOLD) is None
    assert isinstance(canned.LINES["hold"], safe.Spoken) and canned.LINES["hold"].source == "canned"
    assert "ho" not in re.findall(r"[a-z]+", HOLD.lower())        # no "Ho ho" (ho_once)
    assert "hold" in canned.render_all(FakeTTS(), None)


def test_the_hold_line_is_cached_under_its_own_key(tmp_path):
    tts = FakeTTS()
    canned.render_all(tts, tmp_path)
    assert any(p.name.startswith("hold-") and p.suffix == ".npy" for p in tmp_path.iterdir())
    n = len(tts.lines)
    canned.render_all(tts, tmp_path)
    assert len(tts.lines) == n                           # second start: read from the cache, nothing synthesized


# ------------------------------------------------------------------------------------------------ server, page
def test_status_has_a_slow_turns_counter_and_the_protocol_names_the_message():
    s = fast_settings(allowed_hosts=("127.0.0.1", "localhost", "::1", "testserver"))
    brain = SantaBrain(client=FakeClient(), profiles=copy.deepcopy(PROFILES))
    app = create_app(s, brain=brain, stt=FakeSTT(), tts=FakeTTS(), vad_factory=FakeVAD)
    with TestClient(app) as c, c.websocket_connect("/ws"):
        counters = c.get("/status").json()["counters"]
    assert counters["slow_turns"] == 0
    doc = (ROOT / "santa" / "web" / "server.py").read_text().split('"""')[1]
    assert '{"type": "slow"}' in doc and '"where": "ring"' in doc


def test_call_page_loads_the_status_helper_and_uses_it():
    html = (STATIC / "index.html").read_text()
    assert html.index('src="/static/callstatus.js"') < html.index('src="/static/app.js"')
    js = (STATIC / "app.js").read_text()
    assert "SantaStatus.statusText(" in js and 'case "slow"' in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_page_status_text_with_node():
    r = subprocess.run(["node", "--test", str(ROOT / "tests" / "spec" / "js" / "callstatus.test.cjs")],
                       capture_output=True, text=True, timeout=60)
    print(r.stdout[-1500:], r.stderr[-1500:])
    assert r.returncode == 0
