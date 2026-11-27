"""Remove-only, prefix-only speech filter that works sentence by sentence on a token stream (Phase 2 feeds the
sentences to TTS as they come).

    sentences_from_stream(chunks)  -> cleaned sentences, as soon as each one is complete
    speak(sentences)               -> the sentences Santa says: a prefix, never rewritten
    sanitize_ex(text)              -> (heard, why) for a whole reply, built on the two above

Rules (all from santa/spec.py):
  - sentences are spoken in order; nothing is reordered, reworded, demoted or re-punctuated;
  - a sentence that would trip a SAFETY rule (checked on everything spoken so far plus that sentence) is not spoken,
    and nothing after it is either; if nothing was spoken yet, the caller says FALLBACK;
  - the hard cap stops BEFORE a sentence that would go past opener + MAX_CONTENT_SENTENCES or MAX_WORDS. A first
    sentence longer than MAX_WORDS cannot be cut at a sentence boundary, so it gives FALLBACK ("too_long");
  - a trailing teaser ("You know what?") is held back and dropped if nothing follows it (one sentence look-ahead);
  - sentences with numbers are held back until a number-free sentence follows, so a phone number split over several
    sentences is never partly spoken;
  - on a gift turn (the child asked for a gift, is_gift_turn), the pronoun promise rules apply too, and a sentence that
    is only an affirmative ("Yes!") is held for one sentence: dropped with a promise that follows it, spoken with a
    harmless one, dropped if the reply ends on it (P1-3 part B).
Logic adapted from the audit prototype (tools/audit/experiments/prefix_filter_prototype.py), not imported from it.
"""
from typing import Iterable, Iterator

from . import gifts, spec


class Segmenter:
    """Cuts a stream of text chunks into raw segments at final sentence boundaries (spec.next_boundary).
    Gives exactly the segments spec.split_raw gives for the whole text, however the text is chunked."""

    def __init__(self):
        self.buf = ""

    def feed(self, chunk: str) -> list[str]:
        self.buf += chunk or ""
        out = []
        while True:
            b = spec.next_boundary(self.buf)
            if b is None:
                break
            seg, self.buf = self.buf[:b[0]], self.buf[b[1]:]
            if seg.strip():
                out.append(seg)
        return out

    def finish(self) -> list[str]:
        seg, self.buf = self.buf, ""
        return [seg] if seg.strip() else []


def sentences_from_stream(chunks: Iterable[str]) -> Iterator[str]:
    """Cleaned sentences (spec.split_clean order), yielded as soon as each is complete."""
    seg = Segmenter()
    for chunk in chunks:
        for s in seg.feed(chunk):
            yield from spec.sentences_of_segment(s)
    for s in seg.finish():
        yield from spec.sentences_of_segment(s)


def is_gift_turn(child_turn) -> bool:
    """The child's words (never Santa's gift-ask note) ask for or talk about a gift: gifts.talks_gifts, a request shape
    ("Can I have ...?", "Will you bring me ...?", "I really want ...") or a gift noun ("A pony!"). P1-3 part B."""
    if not child_turn or not str(child_turn).strip():
        return False
    return gifts.talks_gifts(str(child_turn)) or spec.is_gift_request(child_turn)


class Gate:
    """The prefix filter as a state machine: push() each cleaned sentence, then finish().
    Both return the sentences that may be spoken now. After a stop, everything else is ignored.

    reason: None, or why speech stopped early: "secret" | "meeting" | "danger" | "price" | "naughty_list" | "promise" |
    "ai_identity" | "blocklist" | "private" (a SAFETY hit) or "too_long". Reaching the normal cap is not a reason."""

    def __init__(self, allow_ho: bool = True, names=(), child_turn=None):
        self.allow_ho = allow_ho       # False: "Ho ho (ho)" is removed (Santa already laughed when he answered)
        self.names = tuple(names or ())   # the active child's name + nicknames: "I'll bring Emma a bike!" (P1-3)
        self.gift_turn = is_gift_turn(child_turn)   # the child's words asked for a gift (P1-3 part B)
        self.child_said = str(child_turn or "")      # lets Santa answer about a topic he never raises ("Day of the Dead")
        self.spoken: list[str] = []
        self.held: list[str] = []      # teasers / number sentences / gift-turn affirmatives waiting for the next one
        self.words = 0
        self.content = 0
        self.stopped = False
        self.reason: str | None = None

    def _stop(self, reason: str | None) -> list[str]:
        self.stopped = True
        self.reason = self.reason or reason
        return []

    def push(self, sentence: str) -> list[str]:
        if not self.allow_ho:
            sentence = spec.strip_ho(sentence)
        if self.stopped or not sentence.strip() or spec.is_bare_action(sentence):
            return []
        pending = self.spoken + self.held
        hit = spec.safety_reason(" ".join(pending + [sentence]), names=self.names, gift_turn=self.gift_turn,
                                 child_said=self.child_said)
        if hit:
            self.held = []    # held sentences may be part of the hit (a number split over sentences): never spoken
            return self._stop(hit)
        is_open = not pending and spec.is_opener(sentence)
        n = len(sentence.split())
        if not pending and n > spec.MAX_WORDS:
            return self._stop("too_long")
        if pending and (self.words + n > spec.MAX_WORDS
                        or (not is_open and self.content + 1 > spec.MAX_CONTENT_SENTENCES)):
            return self._stop(None)
        self.words += n
        self.content += 0 if is_open else 1
        if spec.is_teaser(sentence) or spec.has_number(sentence) or self._held_affirmative(sentence):
            self.held.append(sentence)
            return []
        out, self.held = self.held + [sentence], []
        self.spoken += out
        return out

    def _held_affirmative(self, sentence: str) -> bool:
        """On a gift turn, a bare "Yes!" may be the promise: hold it until the next sentence (P1-3 part B)."""
        return self.gift_turn and spec.is_bare_affirmative(sentence, self.names)

    def finish(self) -> list[str]:
        """Release held sentences, except trailing teasers: those are dropped when anything comes before them
        (a reply that is only a teaser keeps it). On a gift turn, a trailing bare affirmative is always dropped: a lone
        "Yes!" to a gift request is the promise."""
        self.stopped = True
        out = list(self.held)
        while out and (self._held_affirmative(out[-1])
                       or (spec.is_teaser(out[-1]) and (self.spoken or len(out) > 1))):
            out.pop()
        self.held = []
        self.spoken += out
        return out

    @property
    def text(self) -> str:
        return " ".join(self.spoken) if self.spoken else spec.FALLBACK

    @property
    def fallback_reason(self) -> str | None:
        """Why the reply is FALLBACK (None if something was spoken)."""
        return None if self.spoken else (self.reason or "empty")


def speak(sentences: Iterable[str]) -> Iterator[str]:
    """Yield the sentences Santa says (a prefix of `sentences`, minus a trailing teaser)."""
    gate = Gate()
    for s in sentences:
        yield from gate.push(s)
        if gate.stopped:
            break
    yield from gate.finish()


def filter_reply(raw: str, allow_ho: bool = True, names=(), child_turn=None) -> Gate:
    """Run a whole reply through the stream pipeline; the Gate holds spoken, text and reasons.
    child_turn: the child's words this reply answers (P1-3 part B: a gift request turns on the pronoun rules)."""
    gate = Gate(allow_ho=allow_ho, names=names, child_turn=child_turn)
    for s in sentences_from_stream([raw]):
        gate.push(s)
        if gate.stopped:
            break
    gate.finish()
    return gate


def why_code(reason: str | None) -> str | None:
    """Old sanitize_ex codes: "private_output" | "blocklist" | "empty" | "too_long"."""
    if reason is None:
        return None
    return {"private": "private_output", "empty": "empty", "too_long": "too_long"}.get(reason, "blocklist")


def sanitize_ex(text: str, allow_ho: bool = True) -> tuple[str, str | None]:
    """(what the child hears, None or why it is FALLBACK)."""
    gate = filter_reply(text, allow_ho)
    return gate.text, why_code(gate.fallback_reason)
