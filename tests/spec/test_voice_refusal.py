"""P7-3: "the voice refuses unchecked text", on the real voice classes and on the call's refusal path.

1. KokoroTTS.synth, KokoroTTS.synth_at and PocketTTS.synth are built WITHOUT loading a model (object.__new__ plus the
   attributes __init__ would set). The engine is a stub that fails the test if it is called. A plain str, and a
   Spoken made by hand that holds a gift promise, must raise UnsafeForTTS before the engine is touched.
2. A call (test_stage_h fakes, real CallSession) whose brain hands the session a sentence the voice refuses, as if
   the gate had missed it. Refused first sentence: the child hears the fallback line and nothing else. Refused later
   sentence: nothing after it is spoken. Either way the call returns to listening and the refusal is counted
   (session counters["tripwire"] and safe.tripwire_hits).
"""
import _support  # noqa: F401  (temp profiles; must come first)

import asyncio
import copy
from collections import OrderedDict
from types import SimpleNamespace

import numpy as np
import pytest

from _support import FakeClient
from santa import spec
from santa.web import safe
from santa.web.brain_adapter import ReplyInfo, SantaBrain
from santa.web.session import State
from santa.web.tts import SR, KokoroTTS, PocketTTS
from test_stage_h import PROFILES, make, say, start_call, until, wait_mic_open

FB = spec.FALLBACK
PROMISE = "I will bring you a puppy!"


# ================================================================================ 1. the real voice classes
class EngineTouched(AssertionError):
    pass


class FailingKokoro:
    """kokoro_onnx.Kokoro stand-in: any call fails the test."""
    voices = {"am_santa": np.zeros(4, dtype=np.float32)}

    def create(self, *a, **kw):
        raise EngineTouched(f"Kokoro.create called with {a!r}")


class RecordingKokoro(FailingKokoro):
    def __init__(self):
        self.calls = []

    def create(self, text, **kw):
        self.calls.append(text)
        return np.zeros(240, dtype=np.float32), SR


class FailingPocket:
    sample_rate = SR

    def generate_audio(self, *a, **kw):
        raise EngineTouched(f"TTSModel.generate_audio called with {a!r}")


class RecordingPocket(FailingPocket):
    def __init__(self):
        self.calls = []

    def generate_audio(self, state, text):
        self.calls.append(text)
        return SimpleNamespace(numpy=lambda: np.zeros(240, dtype=np.float32))


def kokoro(engine):
    t = object.__new__(KokoroTTS)       # no __init__: no onnxruntime session, no model file
    t.k, t.voice, t.speed, t._style, t._cache = engine, "am_santa", 1.0, "am_santa", OrderedDict()
    return t


def pocket(engine):
    t = object.__new__(PocketTTS)       # no __init__: no pocket_tts import, no weights
    t.model, t.voice, t.speed, t.state = engine, "alba", None, object()
    return t


VOICES = {
    "kokoro.synth": (kokoro, FailingKokoro, RecordingKokoro, lambda t, line: t.synth(line)),
    "kokoro.synth_at": (kokoro, FailingKokoro, RecordingKokoro, lambda t, line: t.synth_at(line, 0.8)),
    "pocket.synth": (pocket, FailingPocket, RecordingPocket, lambda t, line: t.synth(line)),
}


def _hand_made_promise():
    s = safe.Spoken(PROMISE)            # built by hand, as if approved: the tripwire must still stop it
    s.source = "gate"
    return s


@pytest.mark.parametrize("voice", list(VOICES))
@pytest.mark.parametrize("line", [lambda: "Hello there!", lambda: "I will bring you a puppy!", _hand_made_promise],
                         ids=["plain-str", "plain-str-promise", "hand-made-Spoken-promise"])
def test_real_voice_refuses_before_the_engine_is_touched(voice, line):
    build, failing, _, call = VOICES[voice]
    t = build(failing())
    hits = safe.tripwire_hits
    with pytest.raises(safe.UnsafeForTTS):
        call(t, line())
    assert safe.tripwire_hits == hits + 1


@pytest.mark.parametrize("voice", list(VOICES))
def test_real_voice_speaks_an_approved_line(voice):
    """Control: the instances above are good enough to reach the engine, so the refusals are not an accident of how
    they were built."""
    build, _, recording, call = VOICES[voice]
    eng = recording()
    t = build(eng)
    out = call(t, safe.from_gate("Do you like snow?"))
    assert eng.calls == ["Do you like snow?"]
    assert isinstance(out, np.ndarray) and out.dtype == np.float32


# ================================================================================ 2. the call when the voice refuses
class LeakyBrain(SantaBrain):
    """The real brain adapter (history, profiles, calls) with a reply that hands the session fixed sentences, as if the
    speech gate had let one through that the voice's tripwire refuses."""

    def __init__(self, script):
        super().__init__(client=FakeClient(), profiles=copy.deepcopy(PROFILES))
        self.script = list(script)

    def reply(self, speaker, text, on_sentence, cancel=None):
        for s in self.script:
            on_sentence(s)
        return ReplyInfo(sentences=len(self.script))


def _turn_with(script):
    async def go():
        sess, b, _, stt, tts = make()
        sess.brain = LeakyBrain(script)
        hits = safe.tripwire_hits
        await start_call(sess)
        n0, t0 = len(tts.lines), sess.counters["tts_lines"]
        await say(sess, 1.0)
        await until(lambda: sess.counters["turns"] == 1)
        await wait_mic_open(sess)               # back to listening, mic open
        lines = tts.lines[n0:]
        state, counters = sess.state, dict(sess.counters)
        counters["tts_lines"] -= t0                 # lines of this reply only (the greeting counts too)
        await sess.hangup()
        await until(lambda: sess.state == State.IDLE)
        return lines, state, counters, safe.tripwire_hits - hits
    return asyncio.run(go())


def test_voice_refuses_the_first_sentence_child_hears_only_the_fallback_line():
    lines, state, counters, hits = _turn_with([PROMISE, "Do you like snow?", "The elves say hi!"])
    assert lines == [FB]
    assert state == State.LISTENING
    assert counters["tripwire"] == 1 and hits == 1
    assert counters["tts_lines"] == 1


def test_voice_refuses_a_later_sentence_nothing_after_it_is_spoken():
    lines, state, counters, hits = _turn_with(["Hello Emma!", PROMISE, "Do you like snow?"])
    assert lines == ["Hello Emma!"]
    assert state == State.LISTENING
    assert counters["tripwire"] == 1 and hits == 1
    assert counters["tts_lines"] == 1


def test_no_refusal_no_tripwire_count():
    """Control for the two tests above: the same call with safe sentences speaks them all and counts nothing."""
    lines, state, counters, hits = _turn_with(["Hello Emma!", "Do you like snow?"])
    assert lines == ["Hello Emma!", "Do you like snow?"]
    assert state == State.LISTENING
    assert counters.get("tripwire", 0) == 0 and hits == 0
