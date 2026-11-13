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
    sentences is never partly spoken.
Logic adapted from the audit prototype (tools/audit/experiments/prefix_filter_prototype.py), not imported from it.
"""
from typing import Iterable, Iterator

from . import spec


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


class Gate:
    """The prefix filter as a state machine: push() each cleaned sentence, then finish().
    Both return the sentences that may be spoken now. After a stop, everything else is ignored.

    reason: None, or why speech stopped early: "naughty_list" | "promise" | "ai_identity" | "blocklist" | "private"
    (a SAFETY hit) or "too_long". Reaching the normal cap is not a reason."""

    def __init__(self, allow_ho: bool = True, names=()):
        self.allow_ho = allow_ho       # False: "Ho ho (ho)" is removed (Santa already laughed when he answered)
        self.names = tuple(names or ())   # the active child's name + nicknames: "I'll bring Emma a bike!" (P1-3)
        self.spoken: list[str] = []
        self.held: list[str] = []      # teasers / number sentences waiting for a following sentence
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
        hit = spec.safety_reason(" ".join(pending + [sentence]), names=self.names)
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
        if spec.is_teaser(sentence) or spec.has_number(sentence):
            self.held.append(sentence)
            return []
        out, self.held = self.held + [sentence], []
        self.spoken += out
        return out

    def finish(self) -> list[str]:
        """Release held sentences, except trailing teasers: those are dropped when anything comes before them
        (a reply that is only a teaser keeps it)."""
        self.stopped = True
        out = list(self.held)
        while out and spec.is_teaser(out[-1]) and (self.spoken or len(out) > 1):
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


def filter_reply(raw: str, allow_ho: bool = True, names=()) -> Gate:
    """Run a whole reply through the stream pipeline; the Gate holds spoken, text and reasons."""
    gate = Gate(allow_ho=allow_ho, names=names)
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
