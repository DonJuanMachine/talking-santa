"""Santa's brain: one object that holds history + memory and produces replies.

    reply_stream(speaker, text)  yields the sentences Santa says, as soon as each is safe (Phase 2 feeds TTS)
    reply_ex(speaker, text)      -> Reply (typed result: text, raw, spoken, reason, error, shape, timings)
    reply(speaker, text)         -> str (reply_ex(...).text), for old callers
    remember(speaker, text)      fact extraction + save; call it AFTER the reply was spoken (it is a second model
                                 call and must not delay Santa's answer)

Prompt layout (cache-friendly, measured in tools/probes/out/latency.md): the system prompt is the same for the whole
session (persona + every child's name and age, no facts); the active child's facts are a short note on the current
user turn only (never stored in history); history is trimmed in blocks so the prefix stays identical for several turns.
"""
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterator

from openai import DefaultHttpxClient, OpenAI, Timeout

from . import arc, calllog, config, cues, gifts, guide, memory, persona, safety, songs, spec, speech
from .persona import build_system_prompt

# A child's name: letters (accents ok), then letters/digits/'/-. e.g. Emma, Zoë, Mary-Kate
NAME_RE = r"[^\W\d_][\w'-]{1,20}"

# Fail fast: if the model runner hangs, Santa gives up after config.REQUEST_TIMEOUT (15 s) and never retries.
# A cold model load takes longer than that, so warm_up() (long timeout) runs first when the model may be unloaded.
REQUEST_TIMEOUT = config.REQUEST_TIMEOUT


def _now() -> float:
    return time.monotonic()


@dataclass
class Reply:
    """One turn. text = what the child hears (FALLBACK when nothing could be spoken, or the topic's line when an
    intent rule stopped the reply: brain._stop_line).
    spoken: the gate's sentences the child heard, in order (never FALLBACK or a topic line).
    safety_tail: a SAFETY rule stopped the reply after `spoken`, so FALLBACK (or the topic line) was said after them
      (P1-2); then text = spoken + that line.
    reason: None for a complete normal reply; otherwise why speech stopped early or fell back:
      "model_error" | "empty_stream" | "nothing_left_after_filter" | "blocklist:<rule>" | "private_output" | "too_long"
    error: the model/transport error message, if any. shape: spec.shape_flags(raw) (measured, not enforced)."""
    text: str
    raw: str = ""
    spoken: list[str] = field(default_factory=list)
    safety_tail: bool = False
    reason: str | None = None
    error: str | None = None
    shape: list[str] = field(default_factory=list)
    ttft: float = 0.0
    first_sentence_s: float = 0.0
    total: float = 0.0

    @property
    def fallback(self) -> bool:
        return not self.spoken


def _reason_code(gate_reason: str | None) -> str | None:
    if gate_reason is None:
        return None
    if gate_reason == "private":
        return "private_output"
    if gate_reason == "too_long":
        return "too_long"
    return f"blocklist:{gate_reason}"


def _safety_stop(gate: speech.Gate) -> bool:
    """The gate stopped on a SAFETY rule (a spec.safety_reason hit). Not the length cap (reason None) and not a first
    sentence over MAX_WORDS ("too_long"): those are limits, not safety stops (P1-2)."""
    return gate.stopped and gate.reason not in (None, "too_long")


def _stop_line(gate: speech.Gate) -> str:
    """What Santa says after a SAFETY stop, or when nothing could be spoken: the topic's line when an intent rule
    stopped the reply ("meeting", "secret", "danger", "price": persona.TOPIC_LINES), else FALLBACK."""
    return persona.TOPIC_LINES.get(gate.reason or "", safety.FALLBACK)


_LEGACY_WHY = {"empty": "nothing_left_after_filter", "blocklist": "blocklist", "private_output": "private_output",
               "too_long": "too_long"}


_SUMMARY_MIN_TURNS = 2      # end_call: a child who spoke fewer times than this gets no "Last call" fact
_SUMMARY_MAX_LINES = 8      # end_call: only a child's last few turns are shown to the model


class Santa:
    def __init__(self, model: str = config.MODEL, base_url: str = config.BASE_URL, client=None, profiles=None,
                 call_log: bool = False):
        # trust_env=False: never route the model call through an HTTP proxy from the environment (I1).
        self.client = client if client is not None else OpenAI(
            base_url=base_url, api_key="not-needed", timeout=Timeout(config.REQUEST_TIMEOUT), max_retries=0,
            http_client=DefaultHttpxClient(trust_env=False))
        self.model = model
        self.profiles = profiles if profiles is not None else memory.load()
        self.history: list[dict] = []   # {"role": "user"|"assistant", "content": str}; facts notes are never stored
        self.active: str | None = None  # whoever is currently talking
        self.log: list[str] = []
        self.last_reply: Reply | None = None
        self.last_raw = ""
        self.last_stats: dict = {}
        self.last_error: str | None = None  # why the last reply was the fallback (None = something was spoken)
        self.last_ok_time: float | None = None       # _now() of the last successful model call
        self.last_warmup_seconds: float | None = None  # how long the last warm_up() took
        self.last_warmup_failed: float | None = None   # _now() when the last warm_up() failed (None after a success)
        self._start = 0                 # history[_start:] is the window sent to the model
        # Stage I conversation arc: per child, this conversation only (a new Santa = a new Call = a fresh arc).
        self.arc: arc.Arc | None = arc.Arc() if arc.enabled() else None
        # Gift question (santa/gifts.py): per child, this conversation only. Off when the arc is on.
        self.gifts: gifts.Gifts | None = gifts.Gifts() if gifts.enabled() else None
        # Conversation guide (santa/guide.py): hello + "how are you" on a registered child's first turn, then one
        # question about what they like. Per child, this conversation only. The nice-list note is for every child.
        self.guide: guide.Guide | None = guide.Guide() if guide.turns_enabled() else None
        self.nice_on = guide.enabled()
        self._turn_guide: str | None = None   # the guide note the current turn carried (None on a song turn)
        self._turn_led = True                 # the child led the current turn: it is not quiet (guide.advance)
        self._turn_fact: str | None = None    # the remembered like the current turn's guide note asks about
        # The call page sets this for each turn: True once Hang up cut the reply off, so the child did not hear it all.
        # Such a turn does not use up the hello or likes note and does not count toward the call log.
        self.cancelled: Callable[[], bool] = lambda: False
        # Time of day on every turn, from this Mac's clock (SANTA_TIME_NOTE=0 turns it off). Tests replace clock.
        self.time_note_on = os.getenv("SANTA_TIME_NOTE", "1").strip() != "0"
        self.clock = datetime.now
        # Gentle mode: after a sad turn, Santa stays soft for a few turns (SANTA_GENTLE=0 turns it off).
        self.gentle_on = os.getenv("SANTA_GENTLE", "1").strip() != "0"
        self._gentle: dict[str, int] = {}   # child key -> gentle turns left
        # Topic notes: when the child talks about meeting Santa, a secret, something risky or money, that turn's note
        # says how to answer (persona.TOPIC_NOTES; SANTA_TOPIC_NOTES=0 turns them off). The spec.INTENTS rules on
        # Santa's side and the topic lines stay on either way.
        self.topics_on = os.getenv("SANTA_TOPIC_NOTES", "1").strip() != "0"
        # A remembered like that happens in certain weather ("likes snow angels") gets persona.WEATHER_FACT_NOTE: a
        # liked thing, not today's weather where the child is. SANTA_WEATHER_NOTE=0 turns it off.
        self.weather_note_on = os.getenv("SANTA_WEATHER_NOTE", "1").strip() != "0"
        # End-of-call memory: what each registered child said this call (their own words, nothing private), so
        # end_call() can save one "Last call: ..." fact. SANTA_CALL_SUMMARY=0 turns it off.
        self.summary_on = os.getenv("SANTA_CALL_SUMMARY", "1").strip() != "0"
        self.said: dict[str, list[str]] = {}
        self._call_ended = False
        # Call log (santa/calllog.py): only a real call (the call page passes call_log=True; chat.py never does).
        # past_calls is read once, at the start of the call, so this call's own entry never shows in its notes.
        self.call_log_on = call_log and calllog.enabled()
        self.past_calls: dict[str, list[datetime]] = calllog.load() if self.call_log_on else {}
        self._call_turns: dict[str, int] = {}
        self._call_first_at: dict[str, datetime] = {}
        self._call_logged: set[str] = set()
        # "Ho ho ho" once: Santa laughs when he answers; after that only when the child sings or tells a joke.
        # SANTA_HO_ONCE=0 lets the model say it whenever it likes (the old behaviour).
        self.ho_once = os.getenv("SANTA_HO_ONCE", "1").strip() != "0"
        # Songs: a child asking Santa to sing gets a real first verse from fixed text (santa/songs.py).
        self.songs_on = songs.enabled()
        self._sung: list[str] = []          # song keys sung in this call
        self._song_offer: tuple[str, str] | None = None   # (child key, song key) Santa offered last turn

    # -- who is talking ---------------------------------------------------
    def set_active(self, name: str) -> str:
        """Switch the active child. Creates a profile if the name is new."""
        known = memory.match_name(self.profiles, name)
        self.active = known or name.strip().title()
        self.profiles.setdefault(self.active, {"facts": []})
        return self.active

    def add_child(self, name: str) -> str | None:
        """Register a new child (the /add command) and make them the active speaker.
        Returns the stored name, or None if it is not a valid name."""
        name = name.strip()
        if not re.fullmatch(NAME_RE, name):
            return None
        known = memory.match_name(self.profiles, name)
        if known and known.casefold() == name.casefold():
            self.active = known
            return known
        self.active = name if not name.islower() else name.title()  # keep "McKenzie"; fix "emma"
        self.profiles.setdefault(self.active, {"facts": []})
        return self.active

    def parse_speaker(self, line: str) -> tuple[str | None, str]:
        """'Emma: hi santa' -> ('Emma', 'hi santa').

        The prefix switches the active child only if it IS a registered child. Any other 'Word:' prefix
        ('Santa:', 'Yes:', a new name) is returned as a one-off guest speaker: nothing is registered or
        remembered (use /add Name for that), and the active child does not change."""
        m = re.match(rf"^\s*({NAME_RE})\s*:\s*(.+)$", line)
        if m:
            prefix, rest = m.group(1), m.group(2).strip()
            known = memory.match_name(self.profiles, prefix)
            if known and (known.casefold() == prefix.casefold()
                          or memory.aliases(self.profiles).get(prefix.casefold()) == known):  # whole prefix, not "Kate" inside "Mary-Kate"
                return self.set_active(known), rest
            return prefix, rest
        return self.active, line.strip()

    # -- prompt -----------------------------------------------------------------
    def system_prompt(self) -> str:
        """The same all session: persona + every child's name and age. No facts (see facts note)."""
        return build_system_prompt(self.profiles, None)

    def _window_start(self) -> int:
        """Start of the history window for the next request. Drops HISTORY_TRIM_BLOCK messages at once (keeping at
        least 4) instead of one per turn, and never starts on an assistant turn (strict chat templates)."""
        hist, start = self.history, self._start
        while start < len(hist) and hist[start]["role"] != "user":
            start += 1
        if len(hist) - start + 1 > config.HISTORY_TURNS:
            start += max(1, min(config.HISTORY_TRIM_BLOCK, len(hist) - start + 1 - 4))
            while start < len(hist) and hist[start]["role"] != "user":
                start += 1
        return start

    def build_messages(self, speaker: str | None, text: str) -> tuple[list[dict], str, bool]:
        """(messages, history label, redacted). Pure given the current state: changes nothing.
        Layout: [system prompt] + history window + [this turn + time note + facts note + arc or gift note of THIS
        speaker, if any]."""
        safe = safety.redact_private(text)
        label = f"{speaker}: {safe}" if speaker else safe
        first = not any(h["role"] == "user" for h in self.history)
        bye = cues.sounds_like_goodbye(text)
        note = persona.time_note(self.clock(), goodbye=bye) if self.time_note_on and (first or bye) else ""
        kind = self._guide_kind(speaker, text)
        if speaker and speaker in self.profiles:
            facts = self.profiles[speaker].get("facts", [])
            note += persona.facts_note(speaker, facts, self.profiles[speaker])
            if self.weather_note_on and any(cues.weather_like(f) for f in (facts or [])[-persona.NOTE_MAX_FACTS:]):
                note += persona.weather_fact_note(speaker)
            # With the guide on, the call log is told once, with the hello (so the welcome back is not repeated).
            if self.call_log_on and (self.guide is None or kind == guide.HELLO):
                note += persona.calls_note(speaker, self.past_calls.get(speaker, []), self.clock(),
                                           calllog.MAX_PER_CHILD)
            if self.arc is not None:
                note += self.arc.note(speaker)
            if kind == guide.HELLO:
                note += persona.hello_note(speaker, again=self.call_log_on and bool(self.past_calls.get(speaker)))
        elif kind == guide.HELLO:   # a guest
            note += persona.guest_hello_note()
        who = self._gift_key(speaker) or gifts.GUEST         # conversation starters (guide.py): any child, guests too
        if kind == guide.KINDNESS:
            note += persona.kindness_note(who)
        elif kind == guide.KIND_REPLY:
            note += persona.kind_reply_note(who, self._family_pick(speaker))
        elif kind == guide.LIKES:
            note += persona.likes_note(who, self._like_fact(speaker))
        elif kind == guide.GIFT:
            note += persona.gift_note(who)
        elif kind == guide.WRAP:
            note += persona.wrap_note(who)
        elif kind == guide.AFTER_BYE:
            note += persona.after_bye_note(who)
        elif kind == guide.WRAP_REPLY:
            note += persona.wrap_reply_note(who, self._wrap_gift(speaker, text), self._guide_fact(speaker, text, kind))
        if self.gentle_on:
            key, sad = self._gift_key(speaker), cues.sounds_sad(text)
            if sad or self._gentle.get(self._child_key(key), 0) > 0:
                note += persona.gentle_note(key or gifts.GUEST, sad)
            if (loss := spec.loss_of(text)) is not None:      # "my dog died": say sorry and name who (GRIEF_NOTE)
                note += persona.grief_note(key or gifts.GUEST, *loss)
        if self.gifts is not None and self.guide is None:   # with the guide on, the wish question is its GIFT starter
            note += self.gifts.note(self._gift_key(speaker), text)
        if self.nice_on and cues.talks_nice_list(text):
            note += persona.nice_note(self._gift_key(speaker) or gifts.GUEST)
        if self.topics_on and (topic := cues.topic(text)) is not None:
            note += persona.topic_note(topic, self._gift_key(speaker) or gifts.GUEST)
        start = self._window_start()
        messages = ([{"role": "system", "content": self.system_prompt()}] + self.history[start:]
                    + [{"role": "user", "content": label + note}])
        return messages, label, safe != text

    def _guide_kind(self, speaker: str | None, text: str) -> str | None:
        """The guide note this turn gets (guide.HELLO, a starter, guide.KIND_REPLY or None). Pure. Guests share one
        slot. Starters wait on a turn the child led (_guide_wait), and need QUIET_TURNS turns without a question."""
        if self.guide is None:
            return None
        key, wait = self._gift_key(speaker), self._guide_wait(speaker, text)
        gift_open = self.gifts is not None and self.gifts.open(key, text)
        return self.guide.kind(key, gentle=wait, led=wait or cues.asks_santa(text), gift_open=gift_open)

    def _guide_wait(self, speaker: str | None, text: str) -> bool:
        """No starter on this turn: the child is sad (or was a moment ago), raises a topic Santa answers with care, or
        tells of a loss (cues.topic, spec.loss_of: "can you come to my house" got "...What is your favorite toy?";
        2026-11-27). The child led there, so the turn does not count as quiet either."""
        k = self._child_key(self._gift_key(speaker))
        return (cues.sounds_sad(text) or (self.gentle_on and self._gentle.get(k, 0) > 0)
                or cues.topic(text) is not None or spec.loss_of(text) is not None)

    def _wrap_gift(self, speaker: str | None, text: str) -> bool:
        """After the wrap-up, a child who wants to talk more is asked the Christmas wish if it was never asked."""
        key = self._gift_key(speaker)
        return (self.guide is not None and guide.GIFT not in self.guide.state(key).done
                and self.gifts is not None and self.gifts.open(key, text))

    def _guide_fact(self, speaker: str | None, text: str, kind: str | None) -> str | None:
        """The remembered like this turn's guide note asks about: the likes starter's pick, or after the wrap-up one
        not asked yet this call (None: a general question, or the wish question)."""
        if kind == guide.LIKES:
            return self._like_fact(speaker)
        if kind == guide.WRAP_REPLY and not self._wrap_gift(speaker, text):
            p = self.profiles.get(speaker) if speaker else None
            asked = self.guide.state(self._gift_key(speaker)).facts_asked
            return guide.pick_fact(p.get("facts", []) if isinstance(p, dict) else [], self._like_seed(speaker), asked)
        return None

    def _like_fact(self, speaker: str | None) -> str | None:
        """The remembered like or pet the likes question asks about (None: a general likes question; always for a
        guest)."""
        p = self.profiles.get(speaker) if speaker else None
        return guide.pick_fact(p.get("facts", []) if isinstance(p, dict) else [], self._like_seed(speaker))

    def _family_pick(self, speaker: str | None) -> str | None:
        """Who Santa suggests the child could hug (guide.pick_family), rotating like the likes question; None for a
        guest or a child with no family list ("someone who needs it")."""
        return guide.pick_family(self.profiles.get(speaker) if speaker else None, self._like_seed(speaker))

    def _like_seed(self, speaker: str) -> int:
        """Which remembered like the likes question picks (guide.pick_fact). The number of earlier calls, so it changes
        every call; but the call log keeps only the newest calllog.MAX_PER_CHILD, and chat.py (or SANTA_CALL_LOG=0) has
        none, so then the date, which changes every day."""
        n = len(self.past_calls.get(speaker, []))
        return n if self.call_log_on and n < calllog.MAX_PER_CHILD else self.clock().toordinal()

    def _names(self, speaker: str | None) -> list[str]:
        """Names for the promise rule (P1-3: "I'll bring Emma a bike!"): the active child's name and registered
        nicknames first, then every other registered child's name, since a sibling may be in the room ("Wren will get
        a pony too!", P4-2). Other children's nicknames are left out: a nickname can be an ordinary word."""
        out: list[str] = []
        if speaker:
            p = self.profiles.get(speaker)
            nicks = p.get("nicknames") if isinstance(p, dict) else None
            out = [speaker] + [n for n in (nicks or []) if isinstance(n, str)]
        return out + [str(n) for n in self.profiles if n != speaker]

    def _gift_key(self, speaker: str | None) -> str | None:
        """Registered children are tracked by name; everyone else shares one guest slot."""
        return speaker if speaker and speaker in self.profiles else None

    @staticmethod
    def _child_key(name: str | None) -> str:
        return name.casefold() if name else ""

    # -- warm-up ----------------------------------------------------------------
    def warm_up(self) -> bool:
        """Make sure the model is loaded AND the session's system prompt is in the server's prompt cache: one tiny
        non-streamed request with the long WARMUP_TIMEOUT. Never raises. Records the duration in
        last_warmup_seconds; on success sets last_ok_time, on failure sets last_error (and returns False)."""
        t0 = time.perf_counter()
        try:
            messages = [{"role": "system", "content": self.system_prompt()}, {"role": "user", "content": "hi"}]
            self.client.with_options(timeout=Timeout(config.WARMUP_TIMEOUT)).chat.completions.create(
                model=self.model, messages=messages, max_tokens=1, temperature=0.0, extra_body=config.EXTRA_BODY)
        except Exception as e:
            self.last_warmup_seconds = time.perf_counter() - t0
            self.last_error = f"warmup_error: {type(e).__name__}: {e}"[:160]
            self.last_warmup_failed = _now()
            return False
        self.last_warmup_seconds = time.perf_counter() - t0
        self.last_ok_time = _now()
        self.last_warmup_failed = None
        self.last_error = None
        return True

    # -- generation ---------------------------------------------------------
    def reply_stream(self, speaker: str | None, text: str) -> Iterator[str]:
        """Yield what Santa says, sentence by sentence (FALLBACK as the only item if nothing can be said, or as the last
        one after a SAFETY stop that followed spoken sentences, P1-2).
        Exactly one model call (plus a warm-up when the model may have been unloaded, unless a warm-up failed less
        than config.WARMUP_RETRY_SECONDS ago). At the end self.last_reply
        holds the Reply; history and log are updated even if the caller stops iterating early."""
        # Build everything that can raise BEFORE touching history, so history keeps strict user/assistant alternation.
        messages, label, _redacted = self.build_messages(speaker, text)
        start = self._window_start()
        self._turn_guide = None
        self._turn_led = True        # a song turn: the child asked for it (reset below for a model turn)
        self._turn_fact = None
        if self.songs_on:
            offer, self._song_offer = self._song_offer, None     # an offer lasts one turn
            who = self._child_key(self._gift_key(speaker))
            if offer and offer[0] == who and songs.says_yes(text) and not songs.asks_for_song(text):
                yield from self._sing(speaker, text, label, start, key=offer[1])
                return
            if songs.asks_for_song(text):
                unknown = songs.title_status(text) == "unknown"
                yield from self._sing(speaker, text, label, start, offer_only=unknown)
                return

        # The model may have been unloaded while Santa sat idle (the normal timeout is too short for a cold load).
        # A warm-up that failed a moment ago is not repeated: on a hung runner it would only wait another
        # WARMUP_TIMEOUT before the request, which has its own short timeout.
        failed = self.last_warmup_failed
        if (self.last_ok_time is None or _now() - self.last_ok_time > config.IDLE_REWARM_SECONDS) and \
                (failed is None or _now() - failed >= config.WARMUP_RETRY_SECONDS):
            self.warm_up()

        self._turn_guide = self._guide_kind(speaker, text)   # the note this model turn carries (songs carry none)
        self._turn_led = self._guide_wait(speaker, text) or cues.asks_santa(text)   # before gentle mode moves on
        self._turn_fact = self._guide_fact(speaker, text, self._turn_guide)
        legacy = safety.legacy()
        # child_turn: the child's own words (never the label or the gift-ask note), for the gift-turn rules (P1-3 part B)
        gate = speech.Gate(allow_ho=not self.ho_once or cues.sings_or_jokes(text), names=self._names(speaker),
                           child_turn=text)
        seg = speech.Segmenter()
        t0 = time.perf_counter()
        first = first_sentence = None
        parts: list[str] = []
        chunks = 0
        error = None
        said: list[str] = []          # model sentences the child heard, in order (FALLBACK is not one)
        # P1-2: a SAFETY stop after spoken sentences would leave the child with a cut-off prefix (the reassurance or
        # the "tell your grown-up" sentence is often the one stopped). FALLBACK follows at once, as one more sentence,
        # through the same door as the nothing-was-said FALLBACK below. At most once; never with the legacy filter.
        tail = False
        try:
            try:
                stream = self.client.chat.completions.create(
                    model=self.model, messages=messages, stream=True,
                    temperature=config.TEMPERATURE, max_tokens=config.MAX_TOKENS,
                    extra_body=config.EXTRA_BODY,
                )
                for ch in stream:
                    piece = ch.choices[0].delta.content if ch.choices else None
                    if not piece:
                        continue
                    first = first if first is not None else time.perf_counter() - t0
                    parts.append(piece)
                    chunks += 1
                    if legacy or gate.stopped:
                        continue      # keep reading: raw is still recorded for measurement
                    for s_raw in seg.feed(piece):
                        for s in spec.sentences_of_segment(s_raw):
                            for out in gate.push(s):
                                first_sentence = first_sentence or time.perf_counter() - t0
                                said.append(out)
                                yield out
                    if said and not tail and _safety_stop(gate):
                        tail = True       # said now, not when the model finishes: no added wait
                        yield _stop_line(gate)
                self.last_ok_time = _now()  # the model answered (a later filter fallback is not a model problem)
            except GeneratorExit:
                raise
            except Exception as e:  # model runner down, timeout, etc. Stay in character.
                error = f"model_error: {type(e).__name__}: {e}"[:160]
                print(f"[model error: {e}]")
            raw = "".join(parts)

            if legacy:
                if error is None and raw.strip():
                    out, why = safety.sanitize_ex(raw)
                    if why is None:
                        first_sentence = time.perf_counter() - t0
                        said.append(out)
                        yield out
            elif error is None:   # a stream cut by an error leaves an unfinished sentence: never spoken
                for s_raw in seg.finish():
                    for s in spec.sentences_of_segment(s_raw):
                        for out in gate.push(s):
                            first_sentence = first_sentence or time.perf_counter() - t0
                            said.append(out)
                            yield out
                if said and not tail and _safety_stop(gate):
                    tail = True
                    yield _stop_line(gate)
            if not legacy:
                for out in gate.finish():
                    first_sentence = first_sentence or time.perf_counter() - t0
                    said.append(out)
                    yield out
            if not said:
                first_sentence = time.perf_counter() - t0
                yield _stop_line(gate)
        finally:
            raw = "".join(parts)
            spoken = list(said)
            if error:
                reason = "model_error"
            elif not raw.strip():
                reason = "empty_stream"
            elif legacy:
                reason = None if spoken else _LEGACY_WHY.get(safety.sanitize_ex(raw)[1], "nothing_left_after_filter")
            else:
                reason = _reason_code(gate.reason) or (None if spoken else "nothing_left_after_filter")
            stop = _stop_line(gate)
            answer = " ".join(spoken + [stop] if tail else spoken) if spoken else stop
            rep = Reply(text=answer, raw=raw, spoken=spoken, safety_tail=tail, reason=reason, error=error,
                        shape=spec.shape_flags(raw), ttft=first or 0.0, first_sentence_s=first_sentence or 0.0,
                        total=time.perf_counter() - t0)
            self.last_reply = rep
            self.last_raw = raw  # unfiltered model output (used by the benchmark)
            self.last_error = (error or reason) if rep.fallback else None
            self.last_stats = {"ttft": rep.ttft, "first_sentence": rep.first_sentence_s, "total": rep.total,
                               "chunks": chunks, "error": self.last_error is not None}
            self._end_turn(speaker, text, label, start, answer, spoken)

    def _end_turn(self, speaker, text, label, start, answer, spoken) -> None:
        """History, the per-child trackers and the log, after every turn (model reply or song).
        History and log get `answer`, everything the child heard (with a P1-2 FALLBACK tail); the arc and gift trackers
        get only the model's spoken sentences (the tail's question is not Santa asking about the wish)."""
        self.history += [{"role": "user", "content": label}, {"role": "assistant", "content": answer}]
        self._start = start
        content = " ".join(spoken)
        if self.arc is not None and spoken and speaker and speaker in self.profiles:
            self.arc.advance(speaker, content)   # only what was actually spoken (never on FALLBACK)
        if self.gifts is not None and spoken:
            self.gifts.advance(self._gift_key(speaker), text, content, held=self._turn_guide == guide.HELLO,
                               carried=None if self.guide is None else self._turn_guide == guide.GIFT)
        heard = bool(spoken) and not self.cancelled()   # Hang up cut the reply off: the child did not hear it
        if self.guide is not None and heard:
            self.guide.advance(self._gift_key(speaker), content, self._turn_guide, self._turn_fact,   # guests: one
                               led=self._turn_led, pick=self._like_fact(speaker))                   # slot (None)
        self._turn_guide = None
        if self.gentle_on and spoken:
            k = self._child_key(self._gift_key(speaker))
            self._gentle[k] = persona.GENTLE_TURNS if cues.sounds_sad(text) else max(0, self._gentle.get(k, 0) - 1)
        self.log.append(f"{label}\nSanta: {answer}\n")
        if self.summary_on and speaker and speaker in self.profiles and safety.redact_private(text) == text:
            self.said.setdefault(speaker, []).append(text)
        if self.call_log_on and heard and speaker and speaker in self.profiles:
            self._log_call_turn(speaker)     # only answered turns: a call where Santa only said FALLBACK never happened

    def _log_call_turn(self, speaker: str) -> None:
        """Call log (call page only): count this registered child's answered turn; on their calllog.MIN_TURNS-th turn, log the
        call once, with the time of their first turn. Logged here, not at Hang up, so a dropped call still counts."""
        n = self._call_turns.get(speaker, 0) + 1
        self._call_turns[speaker] = n
        if n == 1:
            self._call_first_at[speaker] = self.clock()
        if n >= calllog.MIN_TURNS and speaker not in self._call_logged:
            self._call_logged.add(speaker)
            calllog.record(speaker, self._call_first_at[speaker])

    def _sing(self, speaker, text, label, start, key=None, offer_only=False) -> Iterator[str]:
        """The child asked for a song: Santa says a carol's first verse (fixed text, no model call). For a song he does
        not know (offer_only), he says so and offers one he knows instead. Each line is still checked like any spoken
        line. Bookkeeping as for a normal reply, even if the caller stops early."""
        key = key or songs.pick(text, self._sung)
        who = self._child_key(self._gift_key(speaker))
        gentle = self.gentle_on and self._gentle.get(who, 0) > 0
        if not offer_only:
            self._sung.append(key)
        t0 = time.perf_counter()
        said: list[str] = []
        try:
            todo = songs.offer_lines(key, gentle, text) if offer_only else songs.lines(key, gentle)
            for line in todo:
                if spec.safety_reason(line) is None:
                    said.append(line)
                    yield line
            if not said:
                yield safety.FALLBACK
        finally:
            answer = " ".join(said) if said else safety.FALLBACK
            rep = Reply(text=answer, raw=answer, spoken=list(said), reason=None if said else "nothing_left_after_filter",
                        error=None, shape=spec.shape_flags(answer), ttft=0.0, first_sentence_s=0.0,
                        total=time.perf_counter() - t0)
            self.last_reply = rep
            self.last_raw = answer
            self.last_error = None if said else rep.reason
            self.last_stats = {"ttft": 0.0, "first_sentence": 0.0, "total": rep.total, "chunks": 0,
                               "error": not said, "song": key, "offer": offer_only}
            if offer_only and said:
                self._song_offer = (who, key)
            self._end_turn(speaker, text, label, start, answer, list(said))

    def reply_ex(self, speaker: str | None, text: str) -> Reply:
        """Always returns a Reply whose text is safe to say."""
        for _ in self.reply_stream(speaker, text):
            pass
        return self.last_reply

    def reply(self, speaker: str | None, text: str) -> str:
        """Always returns a safe string. self.last_error says why if it is the fallback."""
        return self.reply_ex(speaker, text).text

    # -- memory (after the reply) ---------------------------------------------
    def remember(self, speaker: str | None, child_text: str) -> list[str]:
        """Extract facts from the child's own words and save them. Call AFTER the reply has been spoken.
        Only registered children are remembered, never a turn that was redacted as private, and nothing when the
        model did not answer the turn (the extractor would only time out too). Returns the facts added."""
        if not speaker or speaker not in self.profiles:
            return []
        safe = safety.redact_private(child_text)
        if safe != child_text:
            return []
        if self.last_reply is not None and not self.last_reply.raw:
            return []
        added = [f for f in memory.extract_facts(self.client, self.model, speaker, safe)
                 if memory.add_fact(self.profiles, speaker, f)]
        memory.save(self.profiles)
        return added

    # -- session end ----------------------------------------------------------
    def end_call(self) -> dict[str, str]:
        """Save one "Last call: ..." fact per registered child who talked this call. Call it AFTER Hang up, on the
        brain thread (it makes model calls). Runs once per call; fails soft. Returns {child: summary} saved."""
        if self._call_ended or not self.summary_on:
            return {}
        self._call_ended = True
        if self.last_reply is not None and not self.last_reply.raw:
            return {}                                       # the model did not answer; a summary would only time out
        done: dict[str, str] = {}
        for name, lines in self.said.items():
            if name not in self.profiles or len(lines) < _SUMMARY_MIN_TURNS:
                continue
            summary = memory.summarize_call(self.client, self.model, name, lines[-_SUMMARY_MAX_LINES:])
            if summary and memory.set_last_call(self.profiles, name, summary):
                done[name] = self.profiles[name]["facts"][-1]
        if done:
            memory.save(self.profiles)
        return done

    def save_transcript(self) -> None:
        if not self.log:
            return
        config.TRANSCRIPT_DIR.mkdir(mode=0o700, exist_ok=True)
        config.TRANSCRIPT_DIR.chmod(0o700)           # owner only, also for a folder made before (VULN-015)
        path = config.TRANSCRIPT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.txt"
        path.touch(mode=0o600)
        path.chmod(0o600)
        path.write_text("\n".join(self.log))
