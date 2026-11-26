"""The web app's view of the brain. Calls santa.brain.Santa's public functions only (reply_stream, remember, warm_up,
set_active); nothing in santa/ is re-implemented or changed.

All brain work runs on ONE thread (the session's brain executor), so warm-up, replies, fact extraction and
"Forget last" never overlap and always run in the order they were asked for.

Hang up cancels the model call: Santa gets a client wrapper whose streamed responses stop (and close the HTTP
response) at the next chunk once the turn's cancel event is set. The brain then finishes the turn normally with
whatever it had. A turn hung up before its job starts never calls the model, and one hung up during its warm-up
sends no request (on a hung model runner either would hold the brain thread, and so the next Call, for its timeout).
"""
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from santa import memory
from santa.brain import Santa

from . import canned


@dataclass
class ReplyInfo:
    sentences: int = 0
    fallback: bool = False
    safety_tail: bool = False            # FALLBACK followed spoken sentences after a SAFETY stop (P1-2)
    reason: str | None = None
    cancelled: bool = False
    ttft: float | None = None            # brain's own number (from its request start)
    first_token_at: float | None = None  # time.monotonic() of the first content chunk
    first_sentence_at: float | None = None
    extra: dict = field(default_factory=dict)


class _Turn:
    def __init__(self):
        self.cancel = threading.Event()
        self.first_token_at: float | None = None


class TurnCancelled(Exception):
    """The turn was hung up before its streamed request was sent (the brain treats it like any model error)."""


class CancellableClient:
    """Wraps an OpenAI-compatible client. Only streamed calls are wrapped; everything else passes through."""

    def __init__(self, inner, state=None):
        self._inner = inner
        self._state = state if state is not None else SimpleNamespace(turn=None)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **kw):
        return CancellableClient(self._inner.with_options(**kw), self._state)

    def _create(self, **kw):
        turn = self._state.turn
        if kw.get("stream") and turn is not None and turn.cancel.is_set():
            raise TurnCancelled("hung up before the request")
        res = self._inner.chat.completions.create(**kw)
        if not kw.get("stream"):
            return res
        return self._wrap(res, turn)

    @staticmethod
    def _wrap(stream, turn):
        try:
            for ch in stream:
                if turn is not None and turn.cancel.is_set():
                    break
                if turn is not None and turn.first_token_at is None:
                    piece = ch.choices[0].delta.content if getattr(ch, "choices", None) else None
                    if piece:
                        turn.first_token_at = time.monotonic()
                yield ch
        finally:
            close = getattr(stream, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass


class SantaBrain:
    """One per app. new_call() starts a fresh conversation (history) that keeps the profiles and the warm model."""

    def __init__(self, client=None, profiles=None, model=None):
        from openai import DefaultHttpxClient, OpenAI, Timeout
        from santa import config
        # trust_env=False: never route the model call through an HTTP proxy from the environment (I1).
        inner = client if client is not None else OpenAI(
            base_url=config.BASE_URL, api_key="not-needed", timeout=Timeout(config.REQUEST_TIMEOUT), max_retries=0,
            http_client=DefaultHttpxClient(trust_env=False))
        self.client = CancellableClient(inner)
        self.profiles = profiles if profiles is not None else memory.load()
        self.model = model or config.MODEL
        self.santa = self._fresh()
        self.last_added: dict[str, list[str]] = {}    # child -> facts added by that child's most recent remember()
        self.lock = threading.Lock()

    def _fresh(self) -> Santa:
        return Santa(model=self.model, client=self.client, profiles=self.profiles, call_log=True)   # a real call

    # -- read-only views ------------------------------------------------------------
    def names(self) -> list[str]:
        return [str(n) for n in self.profiles]

    def aliases(self) -> dict[str, str]:
        """{lower-case nickname: child name}"""
        return memory.aliases(self.profiles)

    @property
    def last_ok_time(self):
        return self.santa.last_ok_time

    # -- calls ------------------------------------------------------------------------
    def new_call(self) -> None:
        old = self.santa
        self.santa = self._fresh()
        self.santa.last_ok_time = old.last_ok_time          # the model is as warm as it was
        self.santa.last_warmup_failed = old.last_warmup_failed
        self.santa.history.append({"role": "assistant", "content": canned.GREETING_SAID})   # as chat.py does

    def end_call(self) -> dict:
        """After Hang up: save a one-line "Last call" memory per child. Never raises."""
        try:
            return self.santa.end_call()
        except Exception:
            return {}

    def warm_up(self) -> bool:
        return self.santa.warm_up()

    def reply(self, speaker, text, on_sentence, cancel: threading.Event | None = None) -> ReplyInfo:
        """Blocking. on_sentence(s) gets every sentence reply_stream yields, in order (gate output or FALLBACK)."""
        if cancel is not None and cancel.is_set():
            return ReplyInfo(cancelled=True)        # hung up while this job was queued: no model call, no history
        turn = _Turn()
        if cancel is not None:
            turn.cancel = cancel
        self.client._state.turn = turn
        info = ReplyInfo()
        self.santa.cancelled = turn.cancel.is_set       # a cut-off reply does not count as heard (call log, guide)
        try:
            if speaker:
                self.santa.set_active(speaker)
            for s in self.santa.reply_stream(speaker, text):
                if turn.cancel.is_set():
                    info.cancelled = True
                    continue        # let the brain finish its bookkeeping; nothing more is passed on
                info.first_sentence_at = info.first_sentence_at or time.monotonic()
                info.sentences += 1
                on_sentence(s)
        finally:
            self.client._state.turn = None
            self.santa.cancelled = lambda: False
        r = self.santa.last_reply
        info.cancelled = info.cancelled or turn.cancel.is_set()
        info.fallback, info.reason, info.ttft = r.fallback, r.reason, r.ttft
        info.safety_tail = r.safety_tail
        info.first_token_at = turn.first_token_at
        return info

    # -- memory -----------------------------------------------------------------------
    def remember(self, speaker, text) -> list[str]:
        added = self.santa.remember(speaker, text)
        if speaker and speaker in self.profiles:
            self.last_added[speaker] = list(added)
        return added

    def forget_last(self, child) -> int:
        """Remove the facts that `child`'s most recent remember() added. A second call does nothing."""
        facts = self.last_added.pop(child, []) if child else []
        if not facts or child not in self.profiles:
            return 0
        stored = self.profiles[child].setdefault("facts", [])
        n = 0
        for f in facts:
            if f in stored:
                stored.remove(f)
                n += 1
        if n:
            memory.save(self.profiles)
            memory.save(self.profiles)   # twice: save() keeps the previous file as .bak, which still had the fact
        return n
