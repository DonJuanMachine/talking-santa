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


def _uid(value) -> int:
    """A playback id from the page; anything that is not a small int becomes -1 (matches nothing)."""
    try:
        return int(value) if isinstance(value, (int, float, str)) and abs(int(value)) < 2**31 else -1
    except (ValueError, OverflowError):
        return -1


class State(str, Enum):
    IDLE = "IDLE"
    RINGING = "RINGING"
    GREETING = "GREETING"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    HANGUP = "HANGUP"


def heard_name(text: str, names: list[str], aliases: dict[str, str] | None = None) -> str | None:
    """A registered name (or nickname, via `aliases`) heard exactly once, as a whole word, case-insensitive, and no
    other registered name."""
    counts = {n: len(re.findall(rf"(?<![\w'-]){re.escape(n)}(?![\w'-])", text, re.IGNORECASE)) for n in names}
    for nick, child in (aliases or {}).items():
        counts[child] = counts.get(child, 0) + len(re.findall(rf"(?<![\w'-]){re.escape(nick)}(?![\w'-])", text, re.IGNORECASE))
    hits = [n for n, c in counts.items() if c]
    if len(hits) == 1 and counts[hits[0]] == 1:
        return hits[0]
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
        self.metrics: list[dict] = []
        self.counters = {"calls": 0, "turns": 0, "say_again": 0, "dropped_short": 0, "extend_fired": 0,
                         "fallbacks": 0, "silence_prompts": 0, "silence_hangups": 0, "forget_presses": 0,
                         "frames_dropped_gated": 0, "tts_lines": 0, "cancelled_turns": 0}
        self.hangup_marks: list[dict] = []
        self.closed = False
        self._bg_tasks: set = set()
        self.turn_speaker: str | None = None    # child of the turn being answered (Forget last during a reply)
        self.forget_this_turn = False

    # ------------------------------------------------------------------------------------------- output
    async def send(self, msg: dict) -> None:
        if self.closed:
            return
        try:
            await self._send_json(msg)
        except Exception:
            self.closed = True

    async def send_bytes(self, data: bytes) -> None:
        if self.closed:
            return
        try:
            await self._send_bytes(data)
        except Exception:
            self.closed = True

    async def set_state(self, st: State) -> None:
        self.state = st
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
        self.active = None                                  # every Call starts as guest (PHASE2_NOTES §1)
        # Not awaited: the brain thread runs jobs in order, so new_call() still runs before the warm-up and before
        # any reply, but a Hang up pressed right now is handled at once.
        self._run(self.w.brain, self.brain.new_call)
        self.silence_stage = 0
        await self.set_state(State.RINGING)
        self._start_flow(self._ring_and_greet(epoch))

    async def _ring_and_greet(self, epoch: int) -> None:
        try:
            t0 = self.clock()
            await self.send({"type": "ring_start"})
            warm = self._run(self.w.brain, self.brain.warm_up)
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
            await self.set_state(State.GREETING)
            if not await self.speak_canned("greeting", epoch):
                return
            await self.open_mic()
            self._start_silence_watch(epoch)
        except asyncio.CancelledError:
            pass

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
            who = heard_name(tr.text, names, self.brain.aliases())
            if who:
                self.active = who
            speaker = self.active
            self.turn_speaker, self.forget_this_turn = speaker, False
            m["speaker_known"] = speaker is not None
            await self._reply(tr.text, speaker, m, epoch)
        except asyncio.CancelledError:
            pass
        except Exception as e:                  # never leave the call stuck in THINKING
            log.error("turn failed: %s", type(e).__name__)
            if epoch == self.epoch:
                await self.set_state(State.SPEAKING)
                if await self.speak_canned("say_again", epoch):
                    await self.open_mic()

    async def _reply(self, text: str, speaker, m: dict, epoch: int) -> None:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        done = object()
        cancel = threading.Event()
        self.cancel_event = cancel

        def on_sentence(s):
            loop.call_soon_threadsafe(q.put_nowait, (s, time.monotonic()))

        fut = self._run(self.w.brain, self.brain.reply, speaker, text, on_sentence, cancel)
        fut.add_done_callback(lambda f: loop.call_soon_threadsafe(q.put_nowait, done))
        uid = self._new_uid()
        total = 0
        started = False
        refused = False
        try:
            while True:
                item = await q.get()
                if item is done:
                    break
                sentence, t_released = item
                m.setdefault("first_sentence", t_released)
                line = safe.from_gate(sentence)
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
            m.update(fallback=info.fallback, reason=info.reason, sentences=info.sentences)
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
            if speaker and not info.cancelled and not forget:   # remember AFTER the reply was spoken; brain thread
                rf = self._run(self.w.brain, self.brain.remember, speaker, text)
                rf.add_done_callback(_log_failure)
            await self.open_mic()
        except asyncio.CancelledError:
            cancel.set()
            self.counters["cancelled_turns"] += 1
            raise
        finally:
            if self.cancel_event is cancel:
                self.cancel_event = None

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
        for t in (self.flow, self.silence_task):
            if t is not None and not t.done():
                t.cancel()
        self.closed = True
        self.state = State.IDLE
