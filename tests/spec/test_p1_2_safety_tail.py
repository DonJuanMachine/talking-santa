"""P1-2 (notes/review/findings/p1-child-safety.md, verified.md): when a SAFETY rule stops a reply after Santa has
already spoken some sentences, the child heard a cut-off prefix and lost the reassurance or the "tell your grown-up"
sentence. Now the brain says FALLBACK (the fixed, already checked line that asks the child to tell a grown-up) as one
more sentence, right at the stop, through the same door as the nothing-was-said FALLBACK.

Not for the length cap (a limit, not a safety stop), never twice, never with SANTA_FILTER=legacy. The gate itself is
unchanged (remove-only, prefix-only). One model call, no added wait.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from _support import GOLDEN, FakeClient, _chunk
from santa import brain, config, speech
from santa.spec import FALLBACK as FB
from santa.web import canned, safe
from santa.web.session import State
from test_stage_h import FakeTTS, fast_settings, make, say, start_call, until, wait_state

PROFILES = {"Emma": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": []}, "Ziv": {"age": 4, "facts": []}}

# The first four P1-2 cases of the finding: (raw reply, the prefix the child heard before this fix).
CASES = [
    ("Oh, Leo, that sounds really scary. But there are no monsters under your bed. Let's tell your daddy.",
     ["Oh, Leo, that sounds really scary."]),                                         # comfort, hit in sentence 2
    ("Thank you for telling me, Leo. A gun is not a toy, so let's tell your mommy or daddy right now.",
     ["Thank you for telling me, Leo."]),                                             # an unsafe report
    ("Oh no, Emma. Grandpa is very sick. But he will not die, the doctors are helping him.",
     ["Oh no, Emma.", "Grandpa is very sick."]),                                      # a sick relative (last sentence)
    ("Hmm, let me check my list! You're not on the naughty list, Emma. You're on my nice list!",
     ["Hmm, let me check my list!"]),                                                 # a naughty-list check
]
CAP = "Oh, Leo. That sounds scary. The dark can feel very big. Let's tell your grown-up together."


def santa(replies, chunk=3, profiles=None):
    s = brain.Santa(model="fake", client=FakeClient(list(replies), chunk=chunk),
                    profiles=profiles if profiles is not None else {k: dict(v) for k, v in PROFILES.items()})
    s.last_ok_time = brain._now()   # recently warmed: no warm-up request
    return s


def run(s, speaker="Leo", text="I'm scared"):
    out = list(s.reply_stream(speaker, text))
    return out, s.last_reply


# ------------------------------------------------------------------------------------------------ brain
@pytest.mark.parametrize("chunk", [1, 3, 1000])
@pytest.mark.parametrize("raw,prefix", CASES)
def test_a_safety_stop_after_a_spoken_prefix_ends_with_the_fallback_line(raw, prefix, chunk):
    out, r = run(santa([raw], chunk=chunk))
    assert out == prefix + [FB]
    assert r.spoken == prefix and r.safety_tail and not r.fallback
    assert r.text == " ".join(prefix + [FB])
    assert r.reason.startswith("blocklist:")
    assert speech.filter_reply(raw).text == " ".join(prefix)     # the gate is unchanged


def test_the_fallback_line_is_said_at_the_stop_without_waiting_for_the_model_to_finish():
    """Latency: the line comes right after the stop, while the model is still streaming (its rest is only recorded)."""
    raw, prefix = CASES[0]
    rest = " The elves are busy. The reindeer are asleep. Snow is falling softly."
    reached = []

    class Watching(FakeClient):
        def _create(self, **kw):
            if not kw.get("stream"):
                return super()._create(**kw)
            self.calls.append(kw)
            text = raw + rest

            def gen():
                for i in range(0, len(text), 3):
                    reached.append(i)
                    yield _chunk(text[i:i + 3])
            return gen()

    s = brain.Santa(model="fake", client=Watching(), profiles=dict(PROFILES))
    s.last_ok_time = brain._now()
    it = s.reply_stream("Leo", "I'm scared")
    assert [next(it) for _ in prefix] + [next(it)] == prefix + [FB]
    assert reached[-1] < len(raw) + len(rest) - 3                # the model had not finished
    assert list(it) == []
    assert s.last_reply.raw == raw + rest                        # the rest is still read and recorded


def test_the_length_cap_is_unchanged():
    out, r = run(santa([CAP]))
    assert FB not in out and not r.safety_tail and r.reason is None
    assert " ".join(out) == speech.filter_reply(CAP).text == r.text


def test_a_first_sentence_stop_gives_the_fallback_exactly_once():
    out, r = run(santa(["You're on the naughty list, Emma! But you can try again."]), speaker="Emma")
    assert out == [FB] and r.fallback and not r.safety_tail and r.text == FB


@pytest.mark.parametrize("raw", [
    "Hi Leo! I am ChatGPT! I am ChatGPT again! You're on the naughty list!",    # more hits after the stop
    "Hi Leo! Call 555 123 4567. Bye!",                                           # private: held, then stopped
])
def test_never_a_double_fallback(raw):
    out, r = run(santa([raw]))
    assert out.count(FB) == 1 and out[-1] == FB and out[:-1] == ["Hi Leo!"] and r.safety_tail


def test_never_a_double_fallback_when_the_stream_breaks_after_the_stop():
    raw, prefix = CASES[0]

    class Breaking(FakeClient):
        def _create(self, **kw):
            if not kw.get("stream"):
                return super()._create(**kw)
            self.calls.append(kw)

            def gen():
                for i in range(0, len(raw), 3):
                    yield _chunk(raw[i:i + 3])
                raise ConnectionError("stream cut")
            return gen()

    s = brain.Santa(model="fake", client=Breaking(), profiles=dict(PROFILES))
    s.last_ok_time = brain._now()
    out, r = run(s)
    assert out == prefix + [FB] and r.reason == "model_error" and r.safety_tail


def test_a_mid_stream_error_without_a_safety_stop_is_unchanged():
    class Breaking(FakeClient):
        def _create(self, **kw):
            if not kw.get("stream"):
                return super()._create(**kw)

            def gen():
                yield _chunk("Hi Leo! You are so kind, and")
                raise ConnectionError("stream cut")
            return gen()

    s = brain.Santa(model="fake", client=Breaking(), profiles=dict(PROFILES))
    s.last_ok_time = brain._now()
    out, r = run(s)
    assert out == ["Hi Leo!"] and not r.safety_tail and r.reason == "model_error"


def test_the_added_line_passes_the_canned_check_and_the_tts_tripwire():
    line = safe.canned(FB)
    assert safe.assert_speakable(line) == FB
    assert safe.from_gate(FB) == FB and safe.assert_speakable(safe.from_gate(FB)) == FB


@pytest.mark.parametrize("raw,prefix", CASES + [(CAP, None)])
def test_the_legacy_filter_is_unchanged(raw, prefix, monkeypatch):
    monkeypatch.setattr(config, "SANTA_FILTER", "legacy")
    from santa.legacy import safety as old
    heard, why = old.sanitize_ex(raw)
    out, r = run(santa([raw]))
    assert out == ([heard] if why is None else [FB]) and not r.safety_tail


def test_history_and_log_hold_what_the_child_heard_and_last_call_lines_only_the_childs_words():
    raw, prefix = CASES[0]
    s = santa([raw])
    s.summary_on = True
    for _ in range(2):
        out, r = run(s, "Leo", "there is a monster under my bed")
    heard = " ".join(prefix + [FB])
    assert s.history[-1] == {"role": "assistant", "content": heard} == {"role": "assistant", "content": " ".join(out)}
    assert s.log[-1].endswith(f"Santa: {heard}\n")
    assert s.said["Leo"] == ["there is a monster under my bed"] * 2       # the child's own words, never Santa's
    s.end_call()
    summary_calls = [c for c in s.client.calls if not c.get("stream")]
    assert summary_calls and all(FB not in m["content"] for c in summary_calls for m in c["messages"]
                                 if m["role"] == "user")


def test_the_gift_tracker_gets_only_the_models_sentences():
    raw, prefix = CASES[3]
    s = santa([raw])
    seen = []
    s.gifts = SimpleNamespace(advance=lambda key, text, spoken, held=False, carried=None: seen.append(spoken),
                              note=lambda *a: "", open=lambda *a: False)
    run(s, "Emma", "am I on the naughty list?")
    assert seen == [" ".join(prefix)]


def test_golden_replies_only_the_measured_four_get_the_line_and_never_twice():
    """Every stored reply through the real brain path: FALLBACK at most once, last, and only after a SAFETY stop.
    Measured before the fix: 4 of 1056 replies are SAFETY-stopped after a spoken prefix on this path."""
    tails = 0
    for rec in GOLDEN:
        s = santa([rec["raw"]], profiles={})
        out, r = run(s, rec.get("speaker"), rec.get("child") or "")
        assert out.count(FB) <= 1 and (FB not in out or out[-1] == FB)
        assert r.text == " ".join(out)
        assert r.safety_tail == (len(out) > 1 and out[-1] == FB)
        if r.safety_tail:
            tails += 1
            assert r.reason.startswith("blocklist:") or r.reason == "private_output"
            assert out[:-1] == r.spoken
    assert tails == 4


# ------------------------------------------------------------------------------------------------ web session
def _reply_lines(tts, n0):
    return tts.lines[n0:]


def test_the_web_path_speaks_the_prefix_then_the_line_and_flags_it_in_metrics():
    async def go():
        raw, prefix = CASES[0]
        sess, b, br, stt, tts = make(client=FakeClient(replies=[raw, "Ho ho! Snow is lovely."]))
        hits = safe.tripwire_hits
        await start_call(sess)
        n0 = len(tts.lines)
        await say(sess, 1.0)
        await until(lambda: sess.counters["turns"] == 1)
        lines, hist, m1 = tts.lines[n0:], br.santa.history[-1]["content"], dict(sess.metrics[-1])
        await wait_state(sess, State.LISTENING)
        await say(sess, 1.0)
        await until(lambda: sess.counters["turns"] == 2)
        m2 = dict(sess.metrics[-1])
        msgs = [m for _, m in b.msgs if m["type"] == "metrics"]
        await sess.hangup()
        await wait_state(sess, State.IDLE)
        return prefix, lines, hist, m1, m2, msgs, safe.tripwire_hits - hits, sess.counters.get("tripwire", 0)

    prefix, lines, hist, m1, m2, msgs, hits, trip = asyncio.run(go())
    assert lines == prefix + [FB]
    assert hist == " ".join(lines)                        # history = what the child heard
    assert hits == 0 and trip == 0                        # every line passed assert_speakable
    assert m1["safety_tail"] is True and m1["fallback"] is False
    assert m2["safety_tail"] is False
    assert msgs[0]["safety_tail"] is True and isinstance(msgs[0]["safety_tail"], bool)
    assert not any(FB in str(v) or prefix[0] in str(v) for m in msgs for v in m.values())   # never speech


class TailBlockingTTS(FakeTTS):
    """Once armed, blocks while synthesizing FALLBACK until released (to hang up during the added line)."""

    def __init__(self):
        super().__init__()
        self.armed = False
        self.at_tail = threading.Event()
        self.release = threading.Event()

    def synth(self, line):
        if self.armed and str(line) == FB:
            self.at_tail.set()
            self.release.wait(3)
        return super().synth(line)


def test_hang_up_during_the_added_line_stops_cleanly():
    async def go():
        raw, prefix = CASES[0]
        tts = TailBlockingTTS()
        sess, b, br, stt, _ = make(client=FakeClient(replies=[raw]), tts=tts)
        sent = []
        inner = sess._send_bytes

        async def record(data):
            sent.append((time.monotonic(), int.from_bytes(data[:4], "little")))
            await inner(data)
        sess._send_bytes = record
        await start_call(sess)
        tts.armed = True
        await say(sess, 1.0)
        await until(tts.at_tail.is_set)
        reply_uid = sess.uid
        t = time.monotonic()
        await sess.hangup()
        stop = [tm for tm, m in b.msgs if m["type"] == "stop_audio" and tm >= t][0] - t
        tts.release.set()
        await wait_state(sess, State.IDLE)
        await asyncio.sleep(0.1)
        late = [u for tm, u in sent if tm >= t and u == reply_uid]
        later_starts = [m for tm, m in b.msgs if tm >= t and m["type"] == "audio_start" and "canned" not in m]
        return stop, late, later_starts, dict(sess.counters), sess.state

    stop, late, later_starts, counters, st = asyncio.run(go())
    assert stop < 0.5
    assert late == [] and later_starts == []              # no audio of the added line after Hang up
    assert counters["cancelled_turns"] == 1 and counters.get("tripwire", 0) == 0 and counters["turns"] == 0
    assert st == State.IDLE


def test_the_slow_hold_line_comes_once_before_the_answer_and_never_between_prefix_and_line():
    raw, prefix = CASES[0]

    class Late(FakeClient):
        def _create(self, **kw):
            if kw.get("stream"):
                time.sleep(0.4)                          # past slow_s: the hold line plays first
            return super()._create(**kw)

    async def go():
        sess, b, br, stt, tts = make(settings=fast_settings(slow_s=0.2, hold_every_s=60.0),
                                     client=Late(replies=[raw]))
        await start_call(sess)
        n0 = len(tts.lines)
        await say(sess, 1.0)
        await until(lambda: sess.counters["turns"] == 1, timeout=5)
        lines, hist = tts.lines[n0:], br.santa.history[-1]["content"]
        await sess.hangup()
        await wait_state(sess, State.IDLE)
        return lines, hist

    lines, hist = asyncio.run(go())
    assert lines == [canned.TEXT["hold"]] + prefix + [FB]
    assert hist == " ".join(prefix + [FB])                # the hold line is a filler, never in history
