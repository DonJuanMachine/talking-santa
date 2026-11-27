"""One call screen = one CallSession (sections 2 and 4). asyncio, no I/O of its own: the WebSocket handler passes
messages in, and the session talks back through send_json / send_bytes.

States: IDLE -> RINGING -> GREETING -> LISTENING <-> THINKING -> SPEAKING -> LISTENING ... ; HANGUP -> IDLE.

Threads: STT, TTS and the brain each get one worker thread, so each model is only ever used from one thread and the
event loop never blocks on a model.
"""
import asyncio
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

import numpy as np

from santa.spec import FALLBACK

from . import audio as au
from . import canned, safe
from .endpoint import Dropped, Endpointer, Utterance

log = logging.getLogger("santa.web")
MAX_AUDIO_MSG = 16 * 1024      # bytes per binary WebSocket message (server.py drops bigger); the page sends 1 KiB
TICK_LATE_S = 1.0              # a liveness tick (or the send of one) slower than this by more is logged as a warning
_BOOT = time.time()            # about when this server process started (wall clock, so a sleeping Mac counts)


def _uid(value) -> int:
    """A playback id from the page; anything that is not a small int becomes -1 (matches nothing)."""
    try:
        return int(value) if isinstance(value, (int, float, str)) and abs(int(value)) < 2**31 else -1
    except (ValueError, OverflowError):
        return -1


def _num(value) -> float:
    """A number from the page for the log: rounded, 0 to 10 million, else -1. Never any text, so the page cannot
    write what it likes into the log."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1e7:
        return -1
    return round(value, 1)


class State(str, Enum):
    IDLE = "IDLE"
    RINGING = "RINGING"
    GREETING = "GREETING"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    HANGUP = "HANGUP"


# A child introducing themself: "I'm X", "I am X", "my name is X", "this is X" (P4-4, owner decision), and "it's X"
# ("hi santa it's jonathan", pinned by tests/review/test_memory.py). A name that merely appears in a sentence
# ("Wren, wait your turn.", "tell Wren hi") is not an introduction.
_INTRO = r"(?<![\w'-])(?:i['’]?m|i\s+am|my\s+name\s+is|this\s+is|it['’]s|it\s+is)\s+"


def _spellings(names: list[str], aliases: dict[str, str] | None) -> list[tuple[str, str]]:
    """(spelling, child) for every registered name and nickname."""
    return [(n, n) for n in names] + list((aliases or {}).items())


def _word(spelling: str) -> str:
    return rf"{re.escape(spelling)}(?![\w'’-])"


def mentioned_names(text: str, names: list[str], aliases: dict[str, str] | None = None) -> dict[str, int]:
    """{child: how many times the name or a nickname is heard as a whole word or a possessive ("Wren's"),
    case-insensitive} (heard ones only)."""
    counts: dict[str, int] = {}
    for spelling, child in _spellings(names, aliases):
        c = len(re.findall(rf"(?<![\w'-]){re.escape(spelling)}(?:['’]s)?(?![\w'’-])", text, re.IGNORECASE))
        if c:
            counts[child] = counts.get(child, 0) + c
    return counts


# Words that may surround a bare name answering "Who am I talking to?" ("Hi Santa, Juniper!"); fix round 1b.
_BARE_FILLER = {"hi", "hello", "hey", "santa", "ho"}


def _bare_words(text: str) -> list[str]:
    """Lower-case words without punctuation and without the filler words."""
    words = (w.strip("'’-") for w in re.findall(r"[\w'’-]+", text.lower()))
    return [w for w in words if w and w not in _BARE_FILLER]


def heard_name(text: str, names: list[str], aliases: dict[str, str] | None = None, bare_ok: bool = False) -> str | None:
    """The child who introduced themself ("I'm X", "my name is X", "this is X", "it's X"; X a registered name or
    nickname), when that is the only registered name in the transcript and it is heard exactly once. Otherwise None:
    a name that merely appears in a sentence does not change the speaker (P4-4).
    bare_ok (the caller passes it only while NO child is active, fix round 1b): a name or nickname that is the whole
    utterance, apart from punctuation and hi/hello/hey/santa/ho ("Juniper!", "Hi Santa, Juniper"), also counts."""
    counts = mentioned_names(text, names, aliases)
    if len(counts) != 1:
        return None
    (child, c), = counts.items()
    if c != 1:
        return None
    spellings = [s for s, ch in _spellings(names, aliases) if ch == child]
    if any(re.search(_INTRO + _word(s), text, re.IGNORECASE) for s in spellings):
        return child
    if bare_ok and any(_bare_words(text) == _bare_words(s) for s in spellings):
        return child
    return None


def _log_failure(f) -> None:
    if not f.cancelled() and f.exception() is not None:
        log.error("remember failed: %s", type(f.exception()).__name__)


class Workers:
    """Shared by all sessions of one app (one model each)."""

    def __init__(self):
        self.stt = ThreadPoolExecutor(1, thread_name_prefix="stt")
        self.tts = ThreadPoolExecutor(1, thread_name_prefix="tts")
        self.brain = ThreadPoolExecutor(1, thread_name_prefix="brain")

    def shutdown(self):
        for ex in (self.stt, self.tts, self.brain):
            ex.shutdown(wait=False, cancel_futures=True)


class CallSession:
    def __init__(self, *, brain, stt, tts, vad, settings, send_json, send_bytes, workers: Workers,
                 canned_audio: dict, clock=time.monotonic, on_metrics=None):
        self.brain, self.stt, self.tts, self.vad, self.s = brain, stt, tts, vad, settings
        self._send_json, self._send_bytes = send_json, send_bytes
        self.w = workers
        self.canned_audio = canned_audio
        self.clock = clock
        self.on_metrics = on_metrics
        self.state = State.IDLE
        self.active: str | None = None
        self.epoch = 0                      # bumped by every Call and Hang up: stale work checks it and stops
        self.uid = 0                        # id of Santa's current utterance (audio stream)
        self.flow: asyncio.Task | None = None
        self.cancel_event: threading.Event | None = None
        self.frames = au.FrameBuffer()
        self.endpointer = Endpointer(settings)
        self.mic_open_at: float | None = None   # mic audio is ignored before this time (None = closed)
        self.played: dict[int, asyncio.Event] = {}
        self.started_at: dict[int, float] = {}
        self.last_voice = clock()
        self.silence_stage = 0
        self.silence_task: asyncio.Task | None = None
        self.tick_task: asyncio.Task | None = None
        self.metrics: list[dict] = []
        self.counters = {"calls": 0, "turns": 0, "say_again": 0, "dropped_short": 0, "extend_fired": 0,
                         "fallbacks": 0, "silence_prompts": 0, "silence_hangups": 0, "forget_presses": 0,
                         "frames_dropped_gated": 0, "tts_lines": 0, "cancelled_turns": 0, "slow_turns": 0}
        self.last_hold_at: float | None = None  # when the "hold" line last played in this call (hold_every_s)
        self.hangup_marks: list[dict] = []
        self.closed = False
        self._bg_tasks: set = set()
        self.turn_speaker: str | None = None    # child of the turn being answered (Forget last during a reply)
        self.forget_this_turn = False
        self.call_started: float | None = None  # clock() when the current call began (None while idle)
        self.turns0 = 0                         # counters["turns"] when it began
        self.last_page_msg: float | None = None  # clock() of the last message of any kind from the page
        self.last_tick: float | None = None     # clock() of the last liveness tick sent

    # ------------------------------------------------------------------------------------------- diagnostics
    def note_page_message(self) -> None:
        """The WebSocket handler calls this for every message from the page (audio frames included)."""
        self.last_page_msg = self.clock()

    def diag(self) -> str:
        """Numbers and state names only (no speech, no names): where this session was when something went wrong."""
        now = self.clock()

        def ago(t):
            return "-" if t is None else f"{now - t:.1f}"

        parts = [f"state={self.state.value}",
                 f"call_s={ago(self.call_started)}",
                 f"turns={self.counters['turns'] - self.turns0 if self.call_started is not None else '-'}",
                 f"page_silent_s={ago(self.last_page_msg)}",
                 f"last_tick_s={ago(self.last_tick)}"]
        try:
            ok = self.brain.last_ok_time
            parts.append(f"model_ok_s={'-' if ok is None else f'{time.monotonic() - ok:.0f}'}")
        except Exception:
            pass
        parts.append(f"server_up_h={(time.time() - _BOOT) / 3600:.1f}")
        return " ".join(parts)

    def _send_failed(self, msg_type, exc: Exception) -> None:
        """A send to the page failed: the connection is gone. Say so once, with what it was sending."""
        if not self.closed:
            log.warning("sending to the page failed (%s, sending %s): %s", type(exc).__name__, msg_type, self.diag())
        self.closed = True

    # ------------------------------------------------------------------------------------------- output
    async def send(self, msg: dict) -> None:
        if self.closed:
            return
        try:
            await self._send_json(msg)
        except Exception as e:
            self._send_failed(msg.get("type"), e)

    async def send_bytes(self, data: bytes) -> None:
        if self.closed:
            return
        try:
            await self._send_bytes(data)
        except Exception as e:
            self._send_failed("audio", e)

    async def set_state(self, st: State) -> None:
        self.state = st
        if st == State.IDLE:
            self.call_started = None
        if st != State.LISTENING:
            self.mic_open_at = None
        await self.send({"type": "state", "state": st.value, "active": self.active, "children": self.brain.names()})

    # ------------------------------------------------------------------------------------- helpers
    def _run(self, ex, fn, *a):
        return asyncio.get_running_loop().run_in_executor(ex, fn, *a)

    def _new_uid(self) -> int:
        self.uid += 1
        self.played[self.uid] = asyncio.Event()
        return self.uid

    async def _stream_samples(self, uid: int, samples: np.ndarray, epoch: int) -> bool:
        for msg in au.out_messages(uid, samples):
            if epoch != self.epoch:
                return False
            await self.send_bytes(msg)
        return True

    async def _wait_played(self, uid: int, seconds: float) -> None:
        ev = self.played.get(uid)
        if ev is None:
            return
        try:
            await asyncio.wait_for(ev.wait(), timeout=seconds + self.s.playback_grace_s)
        except asyncio.TimeoutError:
            log.warning("playback_ended not reported for utterance %s; continuing", uid)

    async def speak_canned(self, name: str, epoch: int) -> bool:
        """Play one canned line and wait until the browser has played it. False if the call moved on."""
        samples = self.canned_audio[name]
        uid = self._new_uid()
        self.counters["tts_lines"] += 1
        await self.send({"type": "audio_start", "id": uid, "sr": au.SR_OUT, "canned": name})
        if not await self._stream_samples(uid, samples, epoch):
            return False
        await self.send({"type": "audio_end", "id": uid})
        await self._wait_played(uid, len(samples) / au.SR_OUT)
        return epoch == self.epoch

    async def open_mic(self) -> None:
        """LISTENING, with the mic ignored until echo_guard_ms after Santa's audio ended."""
        self.frames.clear()
        self.endpointer.reset()
        self.vad.reset()
        await self.set_state(State.LISTENING)
        self.mic_open_at = self.clock() + self.s.echo_guard_ms / 1000
        self.last_voice = self.clock()

    def _bg(self, coro) -> None:
        t = asyncio.ensure_future(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)

    def _start_flow(self, coro) -> None:
        self.flow = asyncio.ensure_future(coro)

    # ------------------------------------------------------------------------------------- inputs
    async def handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "call":
            await self.call()
        elif t == "hangup":
            await self.hangup()
        elif t == "set_child":
            await self.set_child(msg.get("name"))
        elif t == "forget_last":
            # runs on the brain thread behind any running work: never hold up the next message (e.g. Hang up)
            self._bg(self.forget_last())
        elif t == "playback_started":
            self.playback_started(_uid(msg.get("id")))
        elif t == "playback_ended":
            self.playback_ended(_uid(msg.get("id")))
        elif t == "hello":
            await self.set_state(self.state)
        elif t == "client_lost":
            self._client_lost(msg)

    def _client_lost(self, msg: dict) -> None:
        """The page ended a call because nothing arrived for a while, then reconnected and says what it saw.
        Logged as numbers and fixed words only: the page cannot put its own text into the log."""
        def word(key, allowed):
            v = msg.get(key)
            return v if isinstance(v, str) and v in allowed else "?"

        shown = word("visible", ("visible", "hidden"))
        page_state = word("state", tuple(s.value for s in State))
        log.warning("the page gave up on the connection: nothing received for %s ms; its checks ran up to %s ms apart; "
                    "unsent bytes %s; tab %s; page state %s",
                    _num(msg.get("silent_ms")), _num(msg.get("check_gap_ms")), _num(msg.get("buffered")),
                    shown, page_state)

    def playback_started(self, uid: int) -> None:
        if uid in self.played:              # only Santa's own utterance ids: a client cannot grow this dict
            self.started_at.setdefault(uid, self.clock())

    def playback_ended(self, uid: int) -> None:
        ev = self.played.get(uid)
        if ev is not None:
            ev.set()

    async def set_child(self, name) -> None:
        names = self.brain.names()
        self.active = name if name in names else None      # "Guest" (or anything unknown) -> guest
        await self.set_state(self.state)

    async def forget_last(self) -> None:
        self.counters["forget_presses"] += 1
        child = self.active
        if self.state in (State.THINKING, State.SPEAKING) and self.turn_speaker is not None:
            # Pressed while Santa is answering: this turn's facts are not saved yet (that happens after he speaks).
            # Skip saving them instead of deleting the previous turn's facts.
            self.forget_this_turn = True
            await self.send({"type": "forgot", "child": self.turn_speaker, "count": 0, "this_turn": True})
            return
        n = await self._run(self.w.brain, self.brain.forget_last, child)
        await self.send({"type": "forgot", "child": child, "count": n})

    # ------------------------------------------------------------------------------------- Call
    async def call(self) -> None:
        if self.state != State.IDLE:
            return                                          # double Call: ignored
        self.epoch += 1
        epoch = self.epoch
        self.counters["calls"] += 1
        self.call_started = self.clock()
        self.turns0 = self.counters["turns"]
        self.last_tick = None
        self.active = None                                  # every Call starts as guest (PHASE2_NOTES §1)
        # Not awaited: the brain thread runs jobs in order, so new_call() still runs before the warm-up and before
        # any reply, but a Hang up pressed right now is handled at once.
        self._run(self.w.brain, self.brain.new_call)
        self.silence_stage = 0
        self.last_hold_at = None
        await self.set_state(State.RINGING)
        log.info("call started: %s", self.diag())
        self._start_ticks()
        self._start_flow(self._ring_and_greet(epoch))

    async def _ring_and_greet(self, epoch: int) -> None:
        try:
            t0 = self.clock()
            await self.send({"type": "ring_start"})
            warm = self._run(self.w.brain, self._warm_up_for, epoch)
            await asyncio.sleep(self.s.ring_min_s)
            left = self.s.ring_max_s - (self.clock() - t0)
            if left > 0 and not warm.done():
                try:
                    await asyncio.wait_for(asyncio.shield(warm), timeout=left)
                except asyncio.TimeoutError:
                    log.warning("warm-up not done after %.1f s of ringing; the first turn will wait", self.s.ring_max_s)
            if epoch != self.epoch:
                return
            await self.send({"type": "ring_stop"})
            if not warm.done():                             # the child's first turn will wait for the model
                await self.send({"type": "slow", "where": "ring"})
            await self.set_state(State.GREETING)
            if not await self.speak_canned("greeting", epoch):
                return
            await self.open_mic()
            self._start_silence_watch(epoch)
        except asyncio.CancelledError:
            pass

    def _warm_up_for(self, epoch: int) -> bool:
        """Brain thread. A warm-up queued by a Call that was hung up before it ran is skipped: on a hung model runner
        it would hold the next Call for a whole warm-up timeout. The next Call queues its own."""
        if epoch != self.epoch:
            return False
        return self.brain.warm_up()

    # ------------------------------------------------------------------------------------- Hang up
    async def hangup(self, reason: str = "button") -> None:
        if self.state == State.IDLE:
            return
        t0 = self.clock()
        if self.state == State.HANGUP:                      # second press during the goodbye: stop at once
            self.epoch += 1
            await self.send({"type": "stop_audio"})
            await self.set_state(State.IDLE)
            return
        from_state = self.state.value
        log.info("call ending (%s): %s", reason, self.diag())
        self.epoch += 1
        epoch = self.epoch
        if self.cancel_event is not None:
            self.cancel_event.set()                         # stops the model stream at its next chunk
        if self.flow is not None and not self.flow.done():
            self.flow.cancel()
        if self.silence_task is not None and not self.silence_task.done() and \
                self.silence_task is not asyncio.current_task():
            self.silence_task.cancel()
        await self.send({"type": "ring_stop"})
        await self.send({"type": "stop_audio"})             # the browser stops every sound it is playing
        await self.set_state(State.HANGUP)
        self.hangup_marks.append({"from": from_state, "reason": reason, "stop_s": self.clock() - t0})
        self._run(self.w.brain, self.brain.end_call)        # queued behind the last remember(), before any new_call()
        self._start_flow(self._goodbye(epoch))

    async def _goodbye(self, epoch: int) -> None:
        try:
            await self.speak_canned("goodbye", epoch)
        except asyncio.CancelledError:
            return
        if epoch == self.epoch:
            await self.set_state(State.IDLE)

    # ------------------------------------------------------------------------------------- silence
    def _start_silence_watch(self, epoch: int) -> None:
        if self.silence_task is None or self.silence_task.done():
            self.silence_task = asyncio.ensure_future(self._silence_watch(epoch))

    async def _silence_watch(self, epoch: int) -> None:
        try:
            while epoch == self.epoch:
                await asyncio.sleep(min(1.0, self.s.silence_prompt_s / 4))
                if self.state != State.LISTENING or self.endpointer.in_speech:
                    continue
                if self.clock() - self.last_voice < self.s.silence_prompt_s:
                    continue
                if self.silence_stage == 0:
                    self.silence_stage = 1
                    self.counters["silence_prompts"] += 1
                    await self.set_state(State.SPEAKING)
                    if not await self.speak_canned("still_here", epoch):
                        return
                    await self.open_mic()
                else:
                    self.counters["silence_hangups"] += 1
                    await self.hangup(reason="silence")
                    return
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------------------------- liveness
    def _start_ticks(self) -> None:
        if self.s.tick_s > 0 and (self.tick_task is None or self.tick_task.done()):
            self.tick_task = asyncio.ensure_future(self._ticks())

    async def _ticks(self) -> None:
        """During a call (any state but IDLE), a tiny message every tick_s, so the page can tell a dead connection
        from a quiet one. Ends when the call is back to IDLE; the next Call starts it again."""
        try:
            prev = self.clock()
            while not self.closed:
                await asyncio.sleep(self.s.tick_s)
                now = self.clock()
                late, prev = now - prev - self.s.tick_s, now
                if self.state == State.IDLE:
                    return
                if late > TICK_LATE_S:      # the loop was blocked: the page may give up (it waits 6 s)
                    log.warning("a liveness tick was %.1f s late (the server was busy): %s", late, self.diag())
                await self.send({"type": "tick"})
                self.last_tick = self.clock()
                if self.last_tick - now > TICK_LATE_S:      # the page is not reading its socket
                    log.warning("sending a liveness tick took %.1f s: %s", self.last_tick - now, self.diag())
                    prev = self.last_tick
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------------------------- mic
    async def audio_in(self, data: bytes) -> None:
        now = self.clock()
        if self.state != State.LISTENING or self.mic_open_at is None or now < self.mic_open_at:
            self.counters["frames_dropped_gated"] += len(data) // (2 * au.FRAME)
            return
        for frame in self.frames.push(data):
            prob = self.vad(frame)
            if prob >= self.s.vad_off:
                self.last_voice = now
                self.silence_stage = 0
            ev = self.endpointer.push(frame, prob, now)
            if isinstance(ev, Utterance):
                self.counters["extend_fired"] = self.endpointer.extend_fired
                await self.set_state(State.THINKING)
                self._start_flow(self._turn(ev, self.epoch))
                return                                       # the rest of this message is after the endpoint
            if isinstance(ev, Dropped):
                self.counters["dropped_short"] += 1
                self.counters["extend_fired"] = self.endpointer.extend_fired

    # ------------------------------------------------------------------------------------- one turn
    async def _turn(self, utt: Utterance, epoch: int) -> None:
        m = {"t_last": utt.t_last, "t_end": utt.t_end, "speech_ms": round(utt.speech_ms),
             "eos_wait_ms": utt.eos_wait_ms, "extended": utt.extended, "forced": utt.forced}
        self.turn_speaker, self.forget_this_turn = None, False
        try:
            if self.s.debug_audio:
                au.write_debug_wav(self.s.debug_audio_dir / f"utt-{int(time.time() * 1000)}.wav", utt.audio)
            names = self.brain.names()
            tr = await self._run(self.w.stt, self.stt.transcribe, utt.audio, names + list(self.brain.aliases()))
            m["stt_done"] = self.clock()
            if epoch != self.epoch:
                return
            if not tr.ok:
                self.counters["say_again"] += 1
                m.update(say_again=True, stt_why=tr.why)
                await self.set_state(State.SPEAKING)
                ok = await self.speak_canned("say_again", epoch)
                self._emit_metrics(m, self.uid)
                if ok:
                    await self.open_mic()
                return
            aliases = self.brain.aliases()
            # no child active yet (every Call starts so): a bare name answers the greeting (fix round 1b)
            who = heard_name(tr.text, names, aliases, bare_ok=self.active is None)
            if who:
                self.active = who
            speaker = self.active
            self.turn_speaker, self.forget_this_turn = speaker, False
            m["speaker_known"] = speaker is not None
            # A turn that names another registered child is answered but not remembered: it may be a grown-up or a
            # sibling talking, and its words must not become the active child's facts (P4-4).
            other = any(c != speaker for c in mentioned_names(tr.text, names, aliases))
            await self._reply(tr.text, speaker, m, epoch, remember=not other)
        except asyncio.CancelledError:
            pass
        except Exception as e:                  # never leave the call stuck in THINKING
            log.error("turn failed: %s", type(e).__name__)
            if epoch == self.epoch:
                await self.set_state(State.SPEAKING)
                if await self.speak_canned("say_again", epoch):
                    await self.open_mic()

    async def _reply(self, text: str, speaker, m: dict, epoch: int, remember: bool = True) -> None:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        done = object()
        cancel = threading.Event()
        self.cancel_event = cancel

        def on_sentence(s):
            loop.call_soon_threadsafe(q.put_nowait, (s, time.monotonic()))

        fut = self._run(self.w.brain, self.brain.reply, speaker, text, on_sentence, cancel)
        fut.add_done_callback(lambda f: loop.call_soon_threadsafe(q.put_nowait, done))
        # Nothing from the brain for slow_s: a marker joins the queue. Anything the brain sends first cancels it.
        slow = object()
        slow_timer = loop.call_later(self.s.slow_s, q.put_nowait, slow) if self.s.slow_s > 0 else None
        heard_any = False
        uid = self._new_uid()
        total = 0
        started = False
        refused = False
        try:
            while True:
                item = await q.get()
                if item is slow:
                    if not heard_any and not await self._slow_turn(epoch):
                        return
                    continue
                heard_any = True
                if slow_timer is not None:
                    slow_timer.cancel()
                if item is done:
                    break
                sentence, t_released = item
                m.setdefault("first_sentence", t_released)
                line = safe.from_gate(sentence, child_said=text)
                if line is None or refused:
                    continue
                try:
                    samples = await self._run(self.w.tts, self.tts.synth, line)
                except safe.UnsafeForTTS:
                    # tripwire (should never fire): nothing after it is spoken, like the gate's own stop
                    refused = True
                    self.counters["tripwire"] = self.counters.get("tripwire", 0) + 1
                    log.error("tripwire refused a sentence")
                    if started:
                        continue
                    samples = await self._run(self.w.tts, self.tts.synth, safe.canned(FALLBACK))
                if epoch != self.epoch:
                    return
                m.setdefault("first_tts", self.clock())
                if not started:
                    started = True
                    await self.set_state(State.SPEAKING)
                    await self.send({"type": "audio_start", "id": uid, "sr": au.SR_OUT})
                self.counters["tts_lines"] += 1
                total += len(samples)
                if not await self._stream_samples(uid, samples, epoch):
                    return
            info = fut.result()
            if info.first_token_at is not None:
                m["first_token"] = info.first_token_at
            # safety_tail: a boolean only (P1-2: a SAFETY stop after Santa had started speaking); never text
            m.update(fallback=info.fallback, safety_tail=info.safety_tail, reason=info.reason, sentences=info.sentences)
            if info.fallback:
                self.counters["fallbacks"] += 1
            if not started:          # nothing speakable came out (cannot happen: the brain yields FALLBACK)
                await self.open_mic()
                return
            await self.send({"type": "audio_end", "id": uid})
            m["spoken_s"] = round(total / au.SR_OUT, 3)
            await self._wait_played(uid, total / au.SR_OUT)
            if epoch != self.epoch:
                return
            self.counters["turns"] += 1
            self._emit_metrics(m, uid)
            forget = self.forget_this_turn       # Forget last pressed while Santa was answering this turn
            self.turn_speaker, self.forget_this_turn = None, False
            if speaker and remember and not info.cancelled and not forget:   # AFTER the reply was spoken; brain thread
                rf = self._run(self.w.brain, self.brain.remember, speaker, text)
                rf.add_done_callback(_log_failure)
            await self.open_mic()
        except asyncio.CancelledError:
            cancel.set()
            self.counters["cancelled_turns"] += 1
            raise
        finally:
            if slow_timer is not None:
                slow_timer.cancel()
            if self.cancel_event is cancel:
                self.cancel_event = None

    async def _slow_turn(self, epoch: int) -> bool:
        """The brain has sent nothing for slow_s (once per turn). Santa says the canned "hold" line (at most once per
        hold_every_s in this call), then the page is told, in THINKING, so its "taking a while" text stays up until
        the answer. Sentences arriving meanwhile wait in the queue. The mic stays closed (it only opens in
        LISTENING). False if the call moved on."""
        self.counters["slow_turns"] += 1
        now = self.clock()
        if self.last_hold_at is None or now - self.last_hold_at >= self.s.hold_every_s:
            self.last_hold_at = now
            await self.set_state(State.SPEAKING)
            if not await self.speak_canned("hold", epoch):
                return False
            await self.set_state(State.THINKING)
        await self.send({"type": "slow"})
        return epoch == self.epoch

    # ------------------------------------------------------------------------------------- metrics (numbers only)
    def _emit_metrics(self, m: dict, uid: int) -> None:
        if uid in self.started_at:
            m["first_played"] = self.started_at[uid]
        base_end, base_last = m["t_end"], m["t_last"]
        rel = {}
        for k in ("stt_done", "first_token", "first_sentence", "first_tts", "first_played"):
            if k in m:
                rel[f"{k}_from_end"] = round(m[k] - base_end, 3)
        if "first_played" in m:
            rel["total_from_last"] = round(m["first_played"] - base_last, 3)
        rel["endpoint_wait"] = round(base_end - base_last, 3)
        out = {k: v for k, v in m.items() if k not in ("t_last", "t_end", "stt_done", "first_token", "first_sentence",
                                                       "first_tts", "first_played")}
        out.update(rel)
        out["extend_fired_total"] = self.endpointer.extend_fired
        self.metrics.append(out)
        log.info("turn %s", json.dumps(out))
        if self.s.metrics_file:
            with open(self.s.metrics_file, "a") as f:
                f.write(json.dumps(out) + "\n")
        if self.on_metrics:
            self.on_metrics(out)
        asyncio.ensure_future(self.send({"type": "metrics", **out}))

    async def close(self) -> None:
        """WebSocket gone: behave like Hang up without the goodbye."""
        self.epoch += 1
        if self.cancel_event is not None:
            self.cancel_event.set()
        for t in (self.flow, self.silence_task, self.tick_task):
            if t is not None and not t.done():
                t.cancel()
        self.closed = True
        self.state = State.IDLE
