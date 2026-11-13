"""P5-1 (with P1-10): a hung model runner. The runner accepts every request and never answers, so each call waits
for its own timeout. The timeouts are scaled down through santa.config (the values the app reads at call time):
W stands for SANTA_WARMUP_TIMEOUT (90 s in the app) and R for SANTA_TIMEOUT (15 s). No model server, no network.

  - a warm-up that failed a moment ago is not repeated inside the next reply (that reply only pays R)
  - a turn hung up before its job starts never calls the model; one hung up during its warm-up sends no request
  - a warm-up queued by a Call that was hung up before it ran is skipped (the next Call queues its own)
  - a healthy runner warms up exactly as before (I9)
"""
import _support  # noqa: F401  (temp profiles; must come first)

import asyncio
import copy
import threading
import time
from types import SimpleNamespace

import pytest

from _support import FakeClient
from santa import brain as brain_mod
from santa import config
from santa.spec import FALLBACK
from santa.web.brain_adapter import SantaBrain
from santa.web.session import State
from test_stage_h import PROFILES, FakeSTT, fast_settings, make, say, start_call, until, wait_state

W, R = 0.6, 0.15        # scaled WARMUP_TIMEOUT and REQUEST_TIMEOUT


class HungRunner(FakeClient):
    """Accepts each request and does not answer: every call blocks on `answer` until its own timeout, then raises (as
    httpx would). Set `answer` and the runner is healthy again. `started` lists "warm" / "request" / "plain" in the
    order the calls began."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.answer = threading.Event()
        self.started: list[str] = []

    def _wait(self, kind, timeout):
        self.started.append(kind)
        if not self.answer.wait(timeout):
            raise TimeoutError(f"{kind} timed out")

    def with_options(self, **opts):
        def create(**kw):
            self.warm_calls.append(kw)
            self._wait("warm", opts["timeout"].read)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="h"))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def _create(self, **kw):
        self._wait("request" if kw.get("stream") else "plain", config.REQUEST_TIMEOUT)
        return super()._create(**kw)

    def counts(self, upto=None):
        seen = self.started[:upto]
        return {"warm": seen.count("warm"), "request": seen.count("request")}


@pytest.fixture
def scaled(monkeypatch):
    monkeypatch.setattr(config, "WARMUP_TIMEOUT", W)
    monkeypatch.setattr(config, "REQUEST_TIMEOUT", R)


def _brain(client):
    b = SantaBrain(client=client, profiles=copy.deepcopy(PROFILES))
    b.new_call()
    return b


# ------------------------------------------------------------------------------------------- a) no second warm-up
def test_failed_warm_up_is_not_repeated_inside_the_same_reply(scaled):
    client = HungRunner()
    b = _brain(client)
    b.warm_up()                                         # the Call's warm-up (session._ring_and_greet) fails after W
    heard = []
    t0 = time.monotonic()
    info = b.reply("Emma", "hi santa", heard.append)
    waited = time.monotonic() - t0
    print(f"\nfirst reply: {client.counts()} waited {waited:.2f} s (W={W}, R={R})")
    assert heard == [FALLBACK] and info.reason == "model_error"
    assert client.counts() == {"warm": 1, "request": 1}
    assert waited < W                                   # the request's own timeout only, not another warm-up


def test_warm_up_runs_again_once_the_retry_window_has_passed(scaled, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(brain_mod, "_now", lambda: now[0])
    monkeypatch.setattr(config, "WARMUP_RETRY_SECONDS", 10.0, raising=False)
    client = HungRunner()
    b = _brain(client)
    b.warm_up()                                         # fails at t=1000
    now[0] = 1009.0
    b.reply("Emma", "hi santa", lambda s: None)         # inside the window: request only
    assert client.counts() == {"warm": 1, "request": 1}
    now[0] = 1011.0
    b.reply("Emma", "are you there", lambda s: None)    # window passed: the model may be loadable again
    assert client.counts() == {"warm": 2, "request": 2}


def test_runner_that_comes_back_inside_the_window_answers_at_once(scaled):
    client = HungRunner(replies=["Ho ho! Snow is lovely!"])
    b = _brain(client)
    b.warm_up()                                         # fails
    client.answer.set()                                 # the runner answers again
    heard = []
    b.reply("Emma", "i like snow", heard.append)
    assert heard and FALLBACK not in heard
    assert client.counts() == {"warm": 1, "request": 1}
    assert b.last_ok_time is not None                   # a later turn takes the normal path again


def test_a_healthy_runner_warms_up_exactly_as_before(monkeypatch):
    """I9: nothing changes when no warm-up has failed (ring warm-up, idle re-warm after IDLE_REWARM_SECONDS)."""
    now = [1000.0]
    monkeypatch.setattr(brain_mod, "_now", lambda: now[0])
    client = FakeClient(replies=["Ho ho! Hello there!"])
    b = _brain(client)
    b.reply("Emma", "hi", lambda s: None)               # never warmed: warm up first
    assert len(client.warm_calls) == 1
    b.reply("Emma", "hi again", lambda s: None)         # warm: straight to the request
    assert len(client.warm_calls) == 1
    now[0] += config.IDLE_REWARM_SECONDS + 1
    b.reply("Emma", "still there", lambda s: None)      # idle too long: warm up again
    assert len(client.warm_calls) == 2 and len(client.santa_calls) == 3


# ------------------------------------------------------------------------------------------- b) cancelled turns
def test_a_turn_cancelled_before_its_job_starts_never_calls_the_model(scaled):
    client = HungRunner()
    b = _brain(client)
    history = list(b.santa.history)
    cancel = threading.Event()
    cancel.set()                                        # Hang up while the job was still queued
    heard = []
    t0 = time.monotonic()
    info = b.reply("Emma", "hi santa", heard.append, cancel)
    print(f"\ncancelled-before-start turn: {client.counts()} took {time.monotonic() - t0:.2f} s")
    assert client.started == [] and heard == [] and info.cancelled
    assert b.santa.history == history                   # the conversation is left as it was


def test_a_turn_hung_up_during_its_warm_up_sends_no_request(scaled):
    client = HungRunner()
    b = _brain(client)                                  # never warmed: the reply warms up first
    cancel = threading.Event()
    heard = []
    t = threading.Thread(target=lambda: b.reply("Emma", "hi santa", heard.append, cancel))
    t0 = time.monotonic()
    t.start()
    deadline = time.monotonic() + 2
    while client.started != ["warm"] and time.monotonic() < deadline:
        time.sleep(0.005)
    cancel.set()                                        # Hang up while the warm-up is still waiting
    t.join(5)
    print(f"\nhung up during warm-up: {client.started} took {time.monotonic() - t0:.2f} s")
    assert client.started == ["warm"] and heard == []
    assert time.monotonic() - t0 < W + R / 2


# ------------------------------------------------------------------------------------------- through the session
def test_hang_up_during_a_hang_then_call_again_does_not_wait_behind_the_cancelled_turn(scaled):
    """Call, the child talks while the Call's warm-up hangs, Hang up, Call again, the child talks: count the model
    calls the brain thread made before the second call's fallback, and how long the child waited."""
    async def go():
        client = HungRunner()
        sess, b, brain, stt, tts = make(client=client, stt=FakeSTT(["hi santa"]))
        await start_call(sess)                          # greeting plays after ring_max_s; warm-up #1 still hanging
        await say(sess, 1.0)
        await until(lambda: sess.cancel_event is not None)   # the reply job is queued behind warm-up #1
        assert client.started == ["warm"]
        await sess.hangup()
        await wait_state(sess, State.IDLE)
        t_call = time.monotonic()
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: FALLBACK in tts.lines, timeout=10)
        waited = time.monotonic() - t_call
        n = len(client.started)
        await sess.hangup()
        await wait_state(sess, State.IDLE)
        return client.counts(n), waited

    counts, waited = asyncio.run(go())
    print(f"\nbefore the second call's fallback: {counts}; Call to fallback {waited:.2f} s (W={W}, R={R})")
    assert counts == {"warm": 2, "request": 1}          # warm-up #1 (already running), the new Call's, one request
    assert waited < 2 * W + R


def test_a_warm_up_queued_by_a_call_that_was_hung_up_is_skipped(scaled):
    """Call, Hang up while ringing, Call, Hang up while ringing, Call: the middle Call's warm-up never started before
    its Hang up, so it is dropped."""
    async def go():
        client = HungRunner()
        sess, b, brain, stt, tts = make(client=client, stt=FakeSTT(["hi santa"]),
                                        settings=fast_settings(ring_min_s=0.05, ring_max_s=0.3))
        for i in range(2):
            await sess.call()
            await until(lambda: b.types().count("ring_start") == i + 1)
            await asyncio.sleep(0.02)                   # the ring flow has queued this Call's warm-up
            assert sess.state == State.RINGING
            await sess.hangup()
            await wait_state(sess, State.IDLE)
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: FALLBACK in tts.lines, timeout=10)
        n = len(client.started)
        await sess.hangup()
        await wait_state(sess, State.IDLE)
        return client.counts(n)

    counts = asyncio.run(go())
    print(f"\nthree Calls, two hung up while ringing: {counts}")
    assert counts == {"warm": 2, "request": 1}          # the first (running) and the last Call's, then one request
