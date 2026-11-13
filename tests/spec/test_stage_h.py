"""Stage H offline tests: the voice web app with injected fake STT, TTS and VAD. The brain is the real Santa with the
FakeClient from _support (no model server), so the real speech gate decides what may be spoken.

Covered: state machine paths, Hang up in every state, double Call, three Calls each resetting to guest, mic gating
and pre-roll, canned lines vs the rule checks, Forget last, an adversarial model stream (nothing unsafe reaches
TTS), the fixed end-of-speech wait and the extend-once rule, low-confidence transcripts, silence handling, name
detection and the idle keep-alive.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import asyncio
import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from _support import FakeClient, _chunk
from santa import memory, spec, speech
from santa.web import canned, safe
from santa.web.audio import FRAME, FRAME_MS
from santa.web.brain_adapter import SantaBrain
from santa.web.endpoint import Dropped, Endpointer, Utterance
from santa.web.session import CallSession, State, Workers, heard_name
from santa.web.settings import Settings
from santa.web.stt import Transcript, judge, name_hint

PROFILES = {"Emma": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": []}, "Ziv": {"age": 4, "facts": []}}


def fast_settings(**kw):
    base = Settings(ring_min_s=0.05, ring_max_s=0.3, echo_guard_ms=20, eos_ms=1200, eos_extend_ms=1800,
                    silence_prompt_s=999, keepalive_s=0, playback_grace_s=1.0, canned_dir=None)
    return replace(base, **kw)


# ------------------------------------------------------------------------------------------------- fakes
class FakeSTT:
    def __init__(self, texts=("hi santa",), delay=0.0, ok=True):
        self.texts, self.delay, self.ok = list(texts), delay, ok
        self.calls = []

    def transcribe(self, audio, names):
        self.calls.append((len(audio), list(names)))
        if self.delay:
            time.sleep(self.delay)
        t = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        if isinstance(t, Transcript):
            return t
        return Transcript(text=t, ok=self.ok)


class FakeTTS:
    """Records every line; refuses anything the real TTS would refuse (same assert_speakable)."""
    sr = 24000

    def __init__(self, seconds_per_word=0.01, delay=0.0):
        self.spw, self.delay = seconds_per_word, delay
        self.lines: list[str] = []

    def synth(self, line):
        text = safe.assert_speakable(line)
        if self.delay:
            time.sleep(self.delay)
        self.lines.append(text)
        return np.zeros(max(1, int(self.sr * self.spw * len(text.split()))), dtype=np.float32)


class FakeVAD:
    """Loud frame = speech."""

    def reset(self):
        pass

    def __call__(self, frame):
        return 0.95 if float(np.abs(frame).mean()) > 0.05 else 0.01


class SlowStreamClient(FakeClient):
    """Streams one word every `gap` seconds (to hang up while the model is still talking)."""

    def __init__(self, text, gap=0.05, **kw):
        super().__init__(**kw)
        self.text, self.gap = text, gap
        self.closed = threading.Event()
        self.chunks_sent = 0

    def _create(self, **kw):
        if not kw.get("stream"):
            return super()._create(**kw)
        self.calls.append(kw)
        client = self

        class S:
            def __iter__(self):
                for w in client.text.split(" "):
                    time.sleep(client.gap)
                    client.chunks_sent += 1
                    yield _chunk(w + " ")

            def close(self):
                client.closed.set()
        return S()


class Browser:
    """Plays audio instantly: playback_started on the first chunk, playback_ended `play_s` after audio_end."""

    def __init__(self, play_s=0.0):
        self.msgs: list[tuple[float, dict]] = []
        self.audio_bytes = 0
        self.play_s = play_s
        self.sess: CallSession | None = None
        self.auto = True

    async def send_json(self, m):
        self.msgs.append((time.monotonic(), m))
        if m["type"] == "audio_end" and self.auto:
            asyncio.get_running_loop().call_later(self.play_s, self.sess.playback_ended, m["id"])

    async def send_bytes(self, b):
        uid = int.from_bytes(b[:4], "little")
        self.audio_bytes += len(b) - 4
        self.sess.playback_started(uid)

    def types(self):
        return [m["type"] for _, m in self.msgs]

    def states(self):
        return [m["state"] for _, m in self.msgs if m["type"] == "state"]


class PlayLog(dict):
    """Canned audio that writes the line into tts.lines when it is played (like a fresh synthesis would)."""

    def __init__(self, tts, d):
        super().__init__(d)
        self.tts = tts

    def __getitem__(self, k):
        self.tts.lines.append(canned.TEXT[k])
        return super().__getitem__(k)


def make(settings=None, client=None, stt=None, tts=None, play_s=0.0, profiles=None):
    import copy
    s = settings or fast_settings()
    brain = SantaBrain(client=client or FakeClient(), profiles=copy.deepcopy(profiles or PROFILES))
    stt = stt or FakeSTT()
    tts = tts or FakeTTS()
    b = Browser(play_s=play_s)
    w = Workers()
    audio = PlayLog(tts, {k: tts.synth(v) for k, v in canned.LINES.items()})
    tts.lines.clear()
    sess = CallSession(brain=brain, stt=stt, tts=tts, vad=FakeVAD(), settings=s, send_json=b.send_json,
                       send_bytes=b.send_bytes, workers=w, canned_audio=audio)
    b.sess = sess
    return sess, b, brain, stt, tts


async def wait_state(sess, st, timeout=3.0):
    t0 = time.monotonic()
    while sess.state != st:
        if time.monotonic() - t0 > timeout:
            raise AssertionError(f"state {sess.state} != {st}")
        await asyncio.sleep(0.005)


async def until(cond, timeout=3.0):
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.005)


def pcm(seconds, loud):
    n = int(16000 * seconds)
    x = (np.full(n, 0.3 if loud else 0.0, dtype=np.float32) * (np.sign(np.sin(np.arange(n))) + 0.01))
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


async def wait_mic_open(sess):
    await wait_state(sess, State.LISTENING)
    await until(lambda: sess.mic_open_at is not None and time.monotonic() >= sess.mic_open_at)


async def say(sess, seconds=1.0, silence=2.0):
    """Child speaks `seconds`, then silence. Frames are pushed at once: the endpointer counts frames, not wall time."""
    await wait_mic_open(sess)
    await sess.audio_in(pcm(0.2, False) + pcm(seconds, True) + pcm(silence, False))


async def start_call(sess):
    await sess.call()
    await wait_mic_open(sess)


# ================================================================================================ canned + safety
def test_canned_lines_are_the_specified_text_and_pass_the_rule_checks():
    assert canned.TEXT == {
        "laugh": "Ho, ho, ho!",                                  # voiced slower, then the greeting (canned.py)
        "greeting": "Hello, hello! It's Santa! Who am I talking to?",
        "say_again": "Hmm, Santa didn't quite hear that. Can you say it again?",
        "still_here": "I'm still here. Take your time.",
        "goodbye": "Bye bye for now! Merry Christmas!",
        "hold": "Hmm, let me think about that.",                 # P5-1: once on a slow turn (test_p5_slow.py)
    }
    for name, text in canned.TEXT.items():
        assert speech.sanitize_ex(text) == (text, None), name
        assert spec.safety_reason(text) is None
        assert isinstance(canned.LINES[name], safe.Spoken)
    goodbye = canned.TEXT["goodbye"]
    assert "?" not in goodbye                              # no question after a goodbye (PHASE2_NOTES §4)
    assert not any(w in goodbye.lower() for w in ("miss", "don't go", "stay", "sad"))


def test_a_canned_line_that_breaks_a_rule_is_refused():
    with pytest.raises(safe.UnsafeForTTS):
        safe.canned("Ho ho! I promise you a puppy!")
    with pytest.raises(safe.UnsafeForTTS):
        safe.canned("You are on the naughty list.")


def test_tts_refuses_plain_strings_and_tripwires_unsafe_text():
    t = FakeTTS()
    with pytest.raises(safe.UnsafeForTTS):
        t.synth("Hello there!")                           # a plain str never came through the gate
    sneaky = safe.Spoken("I will bring you a puppy!")     # constructed by hand: the tripwire still stops it
    with pytest.raises(safe.UnsafeForTTS):
        t.synth(sneaky)
    assert t.lines == []


def test_from_gate_strips_markdown_asterisks_and_emoji_only():
    assert safe.from_gate("**Ho ho ho!** 🎅") == "Ho ho ho!"
    assert safe.from_gate("I love *snow* too!") == "I love snow too!"
    assert safe.from_gate("✨🎄") is None
    assert safe.from_gate("Hello, Emma!") == "Hello, Emma!"


# ================================================================================================ STT helpers
def test_name_hint_is_built_from_registered_names():
    assert name_hint(["Emma", "Leo"]) == "Santa, Emma, Leo."
    assert name_hint([]) == "Santa."


def test_low_confidence_or_empty_transcripts_are_not_ok_and_nothing_is_filtered_by_phrase():
    s = Settings()
    assert not judge("", [], s).ok
    assert not judge("  ...  ", [], s).ok
    assert judge("we went", [{"avg_logprob": -1.4, "no_speech_prob": 0.1}], s).why == "low_logprob"
    assert judge("hmm", [{"avg_logprob": -0.3, "no_speech_prob": 0.95}], s).why == "no_speech"
    ok = judge("Thank you, Santa!", [{"avg_logprob": -0.3, "no_speech_prob": 0.01}], s)
    assert ok.ok and ok.text == "Thank you, Santa!"       # never blacklisted


def test_heard_name_exactly_once_whole_word_case_insensitive():
    names = ["Emma", "Leo", "Ziv"]
    assert heard_name("hi santa i'm emma", names) == "Emma"
    assert heard_name("This is ZIV!", names) == "Ziv"
    assert heard_name("Emma Emma Emma", names) is None              # more than once
    assert heard_name("I'm Emma and that's Leo", names) is None      # two names
    assert heard_name("Emmanuel likes Leonardo", names) is None      # not whole words
    assert heard_name("no names here", names) is None


# ================================================================================================ endpointing
def run_frames(ep, plan, t0=100.0):
    """plan: list of (seconds, loud). Returns [(event, time)]."""
    out, t = [], t0
    for sec, loud in plan:
        for _ in range(int(round(sec * 1000 / FRAME_MS))):
            t += FRAME_MS / 1000
            ev = ep.push(np.full(FRAME, 0.3 if loud else 0.0, dtype=np.float32), 0.95 if loud else 0.01, t)
            if ev is not None:
                out.append((ev, t))
    return out


def utterances(evs):
    return [e for e, _ in evs if isinstance(e, Utterance)]


def test_fixed_wait_ends_the_turn_after_eos_ms_of_silence():
    ep = Endpointer(Settings(eos_ms=1200))
    evs = run_frames(ep, [(0.5, False), (2.0, True), (3.0, False)])
    (u,) = utterances(evs)
    assert u.t_end - u.t_last == pytest.approx(1.2, abs=FRAME_MS / 1000 + 1e-6)
    assert not u.extended and u.eos_wait_ms == 1200


def test_a_pause_shorter_than_the_wait_does_not_end_the_turn():
    ep = Endpointer(Settings(eos_ms=1200))
    evs = run_frames(ep, [(1.6, True), (1.0, False), (1.0, True), (2.0, False)])
    (u,) = utterances(evs)
    assert u.speech_ms == pytest.approx(2600, abs=2 * FRAME_MS)


def test_extend_once_for_short_turns():
    ep = Endpointer(Settings(eos_ms=1200, eos_extend_ms=1800, eos_short_speech_ms=1500))
    evs = run_frames(ep, [(1.0, True), (3.0, False)])
    (u,) = utterances(evs)
    assert u.extended and u.eos_wait_ms == 1800
    assert u.t_end - u.t_last == pytest.approx(1.8, abs=FRAME_MS / 1000 + 1e-6)
    assert ep.extend_fired == 1


def test_extended_wait_keeps_a_child_who_pauses_for_1_5_s():
    ep = Endpointer(Settings(eos_ms=1200, eos_extend_ms=1800, eos_short_speech_ms=1500))
    evs = run_frames(ep, [(0.8, True), (1.5, False), (1.0, True), (3.0, False)])
    (u,) = utterances(evs)
    assert u.speech_ms == pytest.approx(1800, abs=2 * FRAME_MS)    # both pieces in one turn
    assert u.eos_wait_ms == 1200                                     # rule already used: normal wait again
    assert ep.extend_fired == 1


def test_extend_rule_can_be_switched_off():
    ep = Endpointer(Settings(eos_ms=1200, eos_extend=False))
    (u,) = utterances(run_frames(ep, [(1.0, True), (3.0, False)]))
    assert not u.extended and u.t_end - u.t_last == pytest.approx(1.2, abs=FRAME_MS / 1000 + 1e-6)
    assert ep.extend_fired == 0


def test_long_turns_are_not_extended():
    ep = Endpointer(Settings(eos_ms=1200, eos_extend_ms=1800, eos_short_speech_ms=1500))
    (u,) = utterances(run_frames(ep, [(2.0, True), (3.0, False)]))
    assert not u.extended


def test_clips_shorter_than_250ms_are_dropped():
    ep = Endpointer(Settings())
    evs = run_frames(ep, [(0.15, True), (3.0, False)])
    assert utterances(evs) == []
    assert any(isinstance(e, Dropped) for e, _ in evs)


def test_preroll_keeps_300ms_before_the_first_voiced_frame():
    s = Settings(eos_ms=1200, eos_extend=False)
    ep = Endpointer(s)
    (u,) = utterances(run_frames(ep, [(1.0, False), (1.0, True), (2.0, False)]))
    pre = round(np.ceil(s.preroll_ms / FRAME_MS))
    tail = round(np.ceil(s.tail_ms / FRAME_MS))
    voiced = round(1000 / FRAME_MS)
    assert len(u.audio) == (pre + voiced + tail) * FRAME
    assert np.all(u.audio[:pre * FRAME] == 0.0)                       # the quiet pre-roll is in front
    assert np.all(u.audio[pre * FRAME:(pre + 1) * FRAME] == pytest.approx(0.3))


def test_max_utterance_forces_an_end():
    ep = Endpointer(Settings(max_utterance_s=3))
    (u,) = utterances(run_frames(ep, [(5.0, True)]))
    assert u.forced


# ================================================================================================ state machine
def test_call_rings_greets_listens_and_a_turn_goes_through_the_gate():
    async def go():
        sess, b, brain, stt, tts = make(client=FakeClient(replies=["Ho ho ho! Hello there, friend!"]))
        await start_call(sess)
        assert b.states()[:4] == ["IDLE", "RINGING", "GREETING", "LISTENING"] or \
            b.states()[:3] == ["RINGING", "GREETING", "LISTENING"]
        assert "ring_start" in b.types() and "ring_stop" in b.types()
        assert tts.lines[-1] == canned.TEXT["greeting"]
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        await wait_state(sess, State.LISTENING)
        assert tts.lines[-1] == "Hello there, friend!"            # "Ho ho ho!" removed: Santa laughs once
        st = b.states()
        assert st[-3:] == ["THINKING", "SPEAKING", "LISTENING"]
        m = sess.metrics[0]
        for k in ("stt_done_from_end", "first_sentence_from_end", "first_tts_from_end", "first_played_from_end",
                  "total_from_last", "spoken_s"):
            assert k in m, k
        assert not any(isinstance(v, str) and len(v) > 20 for v in m.values())   # numbers only, no text
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_double_call_is_ignored():
    async def go():
        sess, b, *_ = make()
        await sess.call()
        await sess.call()
        await wait_mic_open(sess)
        await sess.call()
        assert sess.counters["calls"] == 1
        assert b.types().count("ring_start") == 1
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_three_consecutive_calls_each_reset_to_guest():
    async def go():
        sess, b, brain, *_ = make()
        for child in ("Emma", "Leo", "Ziv"):
            await sess.call()
            assert sess.active is None
            await wait_mic_open(sess)
            await sess.set_child(child)
            assert sess.active == child
            await sess.hangup()
            await wait_state(sess, State.IDLE)
            assert brain.santa.history[0]["content"] == canned.GREETING_SAID
        await sess.call()
        assert sess.active is None
        await sess.hangup()
        await wait_state(sess, State.IDLE)
        assert sess.counters["calls"] == 4
    asyncio.run(go())


def test_new_call_starts_a_fresh_history_but_keeps_profiles():
    async def go():
        sess, b, brain, *_ = make()
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        await sess.hangup()
        await wait_state(sess, State.IDLE)
        assert len(brain.santa.history) == 3          # greeting + user + assistant
        profiles = brain.profiles
        await sess.call()
        await until(lambda: len(brain.santa.history) == 1)       # new_call() ran on the brain thread
        assert brain.santa.profiles is profiles
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_the_adult_strip_sets_the_child_and_guest_clears_it():
    async def go():
        sess, b, brain, *_ = make()
        await start_call(sess)
        await sess.set_child("Leo")
        assert sess.active == "Leo"
        await sess.set_child(None)
        assert sess.active is None
        await sess.set_child("Nobody")               # not registered -> guest
        assert sess.active is None
        last = [m for _, m in b.msgs if m["type"] == "state"][-1]
        assert last["children"] == ["Emma", "Leo", "Ziv"]
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_a_name_heard_once_sets_the_active_child_and_is_the_speaker():
    async def go():
        client = FakeClient(replies=["Hello Ziv!"])
        sess, b, brain, *_ = make(client=client, stt=FakeSTT(["hi santa this is ziv"]))
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        assert sess.active == "Ziv"
        assert client.santa_calls[-1]["messages"][-1]["content"].startswith("Ziv: ")
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_low_confidence_transcript_gets_say_again_and_never_reaches_the_brain():
    async def go():
        client = FakeClient()
        stt = FakeSTT([Transcript(text="mm", ok=False, why="low_logprob")])
        sess, b, brain, stt, tts = make(client=client, stt=stt)
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: sess.counters["say_again"] == 1)
        await wait_state(sess, State.LISTENING)
        assert tts.lines[-1] == canned.TEXT["say_again"]
        assert client.santa_calls == []
    asyncio.run(go())


# ================================================================================================ mic gating
def test_mic_audio_is_ignored_outside_listening_and_until_after_playback_ended():
    async def go():
        s = fast_settings(echo_guard_ms=300)
        sess, b, *_ = make(settings=s)
        await sess.audio_in(pcm(1.0, True))                 # IDLE
        assert not sess.endpointer.in_speech and sess.endpointer.turns == 0
        b.auto = False                                        # the browser has not finished the greeting yet
        await sess.call()
        await wait_state(sess, State.GREETING)
        await sess.audio_in(pcm(1.0, True) + pcm(2.0, False))
        assert sess.endpointer.turns == 0
        greet_id = max(sess.played)
        sess.playback_ended(greet_id)
        await wait_state(sess, State.LISTENING)
        t_open = time.monotonic()
        await sess.audio_in(pcm(1.0, True) + pcm(2.0, False))   # within 300 ms of playback_ended: ignored
        assert time.monotonic() - t_open < 0.3
        assert sess.endpointer.turns == 0 and sess.state == State.LISTENING
        await asyncio.sleep(0.32)
        await sess.audio_in(pcm(0.1, False) + pcm(1.0, True))   # now heard
        assert sess.endpointer.in_speech
        assert sess.counters["frames_dropped_gated"] > 0
        await sess.hangup()
        await sess.hangup()                                      # skip the goodbye wait (auto playback is off)
        assert sess.state == State.IDLE
    asyncio.run(go())


def test_mic_reopens_with_an_empty_preroll_after_santa_speaks():
    async def go():
        sess, b, *_ = make()
        await start_call(sess)
        assert len(sess.endpointer.preroll) == 0
        await sess.audio_in(pcm(0.5, False))
        assert len(sess.endpointer.preroll) == sess.endpointer.preroll_frames
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        await wait_mic_open(sess)
        assert len(sess.endpointer.preroll) == 0
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


# ================================================================================================ hang up
def _stop_latency(b, t_hang):
    stops = [t for t, m in b.msgs if m["type"] == "stop_audio" and t >= t_hang]
    return stops[0] - t_hang


async def _hangup_and_check(sess, b, tts):
    t = time.monotonic()
    await sess.hangup()
    assert _stop_latency(b, t) < 0.5
    assert sess.state in (State.HANGUP, State.IDLE)
    await wait_state(sess, State.IDLE, timeout=3)
    assert tts.lines[-1] == canned.TEXT["goodbye"]
    return t


def test_hangup_in_idle_does_nothing():
    async def go():
        sess, b, *_ = make()
        await sess.hangup()
        assert sess.state == State.IDLE and "stop_audio" not in b.types()
    asyncio.run(go())


def test_hangup_while_ringing():
    async def go():
        sess, b, brain, stt, tts = make(settings=fast_settings(ring_min_s=1.0, ring_max_s=2.0))
        await sess.call()
        await wait_state(sess, State.RINGING)
        await asyncio.sleep(0.05)
        await _hangup_and_check(sess, b, tts)
        assert canned.TEXT["greeting"] not in tts.lines                     # the greeting never played
        await asyncio.sleep(1.2)
        assert sess.state == State.IDLE                       # the ring flow did not come back
    asyncio.run(go())


def test_hangup_while_greeting():
    async def go():
        sess, b, brain, stt, tts = make(play_s=1.0)
        await sess.call()
        await wait_state(sess, State.GREETING)
        await asyncio.sleep(0.05)
        b.play_s = 0.0
        await _hangup_and_check(sess, b, tts)
    asyncio.run(go())


def test_hangup_while_listening():
    async def go():
        sess, b, brain, stt, tts = make()
        await start_call(sess)
        await _hangup_and_check(sess, b, tts)
    asyncio.run(go())


def test_hangup_while_thinking_in_stt():
    async def go():
        sess, b, brain, stt, tts = make(stt=FakeSTT(delay=0.6))
        await start_call(sess)
        await say(sess, 1.0)
        await wait_state(sess, State.THINKING)
        await _hangup_and_check(sess, b, tts)
        await asyncio.sleep(0.7)
        assert sess.state == State.IDLE and sess.metrics == []
    asyncio.run(go())


def test_hangup_while_the_model_is_streaming_cancels_the_model_call():
    async def go():
        text = "Ho ho! " + " ".join(["Snow is fun"] * 4) + " and very sparkly today friend!"
        client = SlowStreamClient(text, gap=0.08)
        sess, b, brain, stt, tts = make(client=client)
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: client.chunks_sent >= 3)
        sent_before = client.chunks_sent
        t = await _hangup_and_check(sess, b, tts)
        assert client.closed.wait(0.5), "the model stream was not closed within 500 ms"
        assert time.monotonic() - t < 3
        assert client.chunks_sent <= sent_before + 8          # stopped long before the end of the reply
        assert sess.counters["cancelled_turns"] == 1
    asyncio.run(go())


def test_hangup_while_speaking():
    async def go():
        sess, b, brain, stt, tts = make(client=FakeClient(replies=["Ho ho ho! I love snow!"]), play_s=2.0)
        b.play_s = 0.0
        await start_call(sess)
        b.play_s = 2.0
        await say(sess, 1.0)
        await wait_state(sess, State.SPEAKING)
        await asyncio.sleep(0.1)
        b.play_s = 0.0
        await _hangup_and_check(sess, b, tts)
    asyncio.run(go())


def test_hangup_right_after_forget_last_is_not_held_up_by_the_brain_thread():
    """Soak finding: Forget last waits for the brain thread (behind remember()); it must not delay a Hang up."""
    async def go():
        sess, b, brain, stt, tts = make()
        await start_call(sess)
        sess.w.brain.submit(time.sleep, 0.8)            # the brain thread is busy (a fact extraction, say)
        await sess.handle({"type": "forget_last"})
        t = time.monotonic()
        await sess.handle({"type": "hangup"})
        assert _stop_latency(b, t) < 0.1
        await wait_state(sess, State.IDLE, timeout=3)
        await until(lambda: any(m["type"] == "forgot" for _, m in b.msgs), timeout=3)
    asyncio.run(go())


def test_call_is_not_held_up_by_a_busy_brain_thread():
    async def go():
        sess, b, brain, *_ = make()
        sess.w.brain.submit(time.sleep, 0.8)
        t = time.monotonic()
        await sess.handle({"type": "call"})
        assert sess.state == State.RINGING and time.monotonic() - t < 0.1
        await sess.handle({"type": "hangup"})
        assert sess.state == State.HANGUP
        await wait_state(sess, State.IDLE, timeout=3)
    asyncio.run(go())


def test_second_hangup_during_goodbye_goes_straight_to_idle():
    async def go():
        sess, b, brain, stt, tts = make(play_s=2.0)
        b.play_s = 0.0
        await start_call(sess)
        b.play_s = 2.0
        await sess.hangup()
        assert sess.state == State.HANGUP
        t = time.monotonic()
        await sess.hangup()
        assert sess.state == State.IDLE and time.monotonic() - t < 0.5
    asyncio.run(go())


def test_call_works_again_after_every_kind_of_hangup():
    async def go():
        sess, b, *_ = make()
        for _ in range(3):
            await start_call(sess)
            await sess.hangup()
            await wait_state(sess, State.IDLE)
        assert sess.counters["calls"] == 3
    asyncio.run(go())


# ================================================================================================ adversarial stream
ADVERSARIAL = [
    "You're on the naughty list! You get coal!",
    "I will bring you a puppy! Ho ho!",
    "As an AI language model, I cannot do that.",
    "My monster friend has a gun.",
    "Your number is 555 123 4567. Call me!",
    "**Ho ho ho!** 🎅 I promise you a pony!",
    "Ho ho! I'm Gemma, made by Google! Bye!",
]


@pytest.mark.parametrize("raw", ADVERSARIAL)
def test_adversarial_model_stream_never_reaches_tts(raw):
    async def go():
        sess, b, brain, stt, tts = make(client=FakeClient(replies=[raw]))
        await start_call(sess)
        n0 = len(tts.lines)
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        spoken = tts.lines[n0:]
        assert spoken, "something (at least the fallback) must be said"
        for line in spoken:
            assert spec.safety_reason(line) is None, line
            assert not spec.BLOCK_RE.search(line), line
        heard, why = speech.sanitize_ex(raw, allow_ho=False)     # the child said "hi santa": no "Ho ho" (ho_once)
        expected = [safe.from_gate(spec.strip_ho(s)) for s in speech.sentences_from_stream([raw])]
        if why is not None:
            assert spoken == [spec.FALLBACK]                  # the existing fallback
        else:
            assert " ".join(spoken) == heard and all(x in expected for x in spoken)
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_fully_blocked_reply_gives_exactly_the_existing_fallback():
    async def go():
        sess, b, brain, stt, tts = make(client=FakeClient(replies=["You're on the naughty list, Emma."]))
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        assert tts.lines[-1] == spec.FALLBACK
        assert sess.metrics[0]["fallback"] is True
        assert sess.metrics[0]["reason"] == "blocklist:naughty_list"
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_model_error_gives_the_fallback_and_the_call_continues():
    async def go():
        sess, b, brain, stt, tts = make(client=FakeClient(replies=[RuntimeError("runner down")]))
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        await wait_state(sess, State.LISTENING)
        assert tts.lines[-1] == spec.FALLBACK
    asyncio.run(go())


def test_markdown_and_emoji_are_stripped_before_tts():
    async def go():
        sess, b, brain, stt, tts = make(client=FakeClient(replies=["**Ho ho ho!** I love *snow* 🎄 so much!"]))
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        for line in tts.lines:
            assert not any(c in line for c in "*_#`") and "🎄" not in line
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


# ================================================================================================ forget last
def test_forget_last_removes_the_last_remembered_facts_and_a_second_press_does_nothing(tmp_path, monkeypatch):
    path = tmp_path / "profiles.json"
    monkeypatch.setattr(memory.save, "__defaults__", (path,))

    async def go():
        client = FakeClient(replies=["Ho ho! A puppy sounds lovely!"],
                            extract='{"facts": ["has a dog named Rex", "wants a puppy"]}')
        sess, b, brain, *_ = make(client=client, stt=FakeSTT(["i'm emma and my dog rex is gone"]))
        brain.profiles["Emma"]["facts"] = ["likes snow"]
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        await until(lambda: "wants a puppy" in brain.profiles["Emma"]["facts"])
        assert sess.active == "Emma"
        await sess.forget_last()
        forgot = [m for _, m in b.msgs if m["type"] == "forgot"]
        assert forgot[-1] == {"type": "forgot", "child": "Emma", "count": 2}
        assert brain.profiles["Emma"]["facts"] == ["likes snow"]
        saved = json.loads(path.read_text())["children"]["Emma"]["facts"]
        assert saved == ["likes snow"]
        bak = path.with_name(path.name + ".bak")
        assert "Rex" not in bak.read_text()                   # the backup does not keep the forgotten fact
        await sess.forget_last()                               # second press: nothing
        forgot = [m for _, m in b.msgs if m["type"] == "forgot"]
        assert forgot[-1]["count"] == 0
        assert brain.profiles["Emma"]["facts"] == ["likes snow"]
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_forget_last_only_touches_the_active_child(tmp_path, monkeypatch):
    monkeypatch.setattr(memory.save, "__defaults__", (tmp_path / "p.json",))
    brain = SantaBrain(client=FakeClient(extract='{"facts": ["likes trains"]}'),
                       profiles={"Emma": {"facts": []}, "Leo": {"facts": []}})
    brain.reply("Leo", "i like trains", lambda s: None)
    assert brain.remember("Leo", "i like trains") == ["likes trains"]
    assert brain.forget_last("Emma") == 0
    assert brain.forget_last(None) == 0
    assert brain.profiles["Leo"]["facts"] == ["likes trains"]
    assert brain.forget_last("Leo") == 1
    assert brain.profiles["Leo"]["facts"] == []


def test_forget_after_a_remember_that_added_nothing_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(memory.save, "__defaults__", (tmp_path / "p.json",))
    client = FakeClient(extract='{"facts": ["likes trains"]}')
    brain = SantaBrain(client=client, profiles={"Leo": {"facts": []}})
    brain.reply("Leo", "i like trains", lambda s: None)
    brain.remember("Leo", "i like trains")
    client.extract = '{"facts": []}'
    brain.reply("Leo", "hello", lambda s: None)
    assert brain.remember("Leo", "hello") == []
    assert brain.forget_last("Leo") == 0                      # the MOST RECENT remember() added nothing
    assert brain.profiles["Leo"]["facts"] == ["likes trains"]


def test_guest_turns_are_not_remembered():
    async def go():
        client = FakeClient(extract='{"facts": ["likes trains"]}')
        sess, b, brain, *_ = make(client=client, stt=FakeSTT(["i like trains"]))
        await start_call(sess)
        await say(sess, 1.0)
        await until(lambda: len(sess.metrics) == 1)
        await asyncio.sleep(0.05)
        assert all(p["facts"] == [] for p in brain.profiles.values())
        assert not [c for c in client.calls if not c.get("stream")]
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


# ================================================================================================ silence + keep-alive
def test_silence_prompt_then_goodbye_and_hang_up():
    async def go():
        sess, b, brain, stt, tts = make(settings=fast_settings(silence_prompt_s=0.3))
        await start_call(sess)
        await until(lambda: sess.counters["silence_prompts"] == 1, timeout=3)
        await until(lambda: sess.counters["silence_hangups"] == 1, timeout=3)
        await wait_state(sess, State.IDLE)
        lines = tts.lines
        assert lines[-3:] == [canned.TEXT["greeting"], canned.TEXT["still_here"], canned.TEXT["goodbye"]]
    asyncio.run(go())


def test_speech_resets_the_silence_timer():
    async def go():
        sess, b, brain, stt, tts = make(settings=fast_settings(silence_prompt_s=0.5))
        await start_call(sess)
        for _ in range(4):
            await asyncio.sleep(0.25)
            await sess.audio_in(pcm(0.1, True))          # too short to be a turn, but it is a voice
        assert sess.counters["silence_prompts"] == 0
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_keepalive_pings_only_while_no_call_is_active():
    from santa.web.server import Engines

    class B:
        def __init__(self):
            self.pings = 0
            self.last_ok_time = None

        def warm_up(self):
            self.pings += 1
            self.last_ok_time = time.monotonic()
            return True

    async def go():
        eng = Engines(fast_settings(keepalive_s=0.1), brain=B())
        class Busy:
            state = State.LISTENING
        busy = Busy()
        task = asyncio.ensure_future(eng.keepalive_loop())
        await asyncio.sleep(0.5)
        idle_pings = eng.brain.pings
        eng.sessions.add(busy)
        await asyncio.sleep(0.1)
        n = eng.brain.pings
        await asyncio.sleep(0.5)
        assert eng.brain.pings == n                    # no pings during a call
        eng.sessions.discard(busy)
        await asyncio.sleep(0.5)
        task.cancel()
        assert idle_pings >= 2 and eng.brain.pings > n
    asyncio.run(go())


# ================================================================================================ hygiene
def test_brain_files_are_untouched_by_stage_h():
    """santa/ needs no change for Stage H: the app reads names from the profiles and tracks facts itself."""
    import santa.brain as sb
    assert not hasattr(sb.Santa, "forget_last")


def test_server_binds_to_localhost_only():
    assert Settings().host == "127.0.0.1"


def test_debug_audio_is_off_by_default_and_its_folder_is_gitignored():
    from pathlib import Path
    assert Settings().debug_audio is False
    gi = (Path(__file__).resolve().parents[2] / ".gitignore").read_text()
    assert "santa/web/debug_audio/" in gi and "santa/web/.cache/" in gi
