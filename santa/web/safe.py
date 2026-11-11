"""The only door to TTS (section 3: everything spoken passes the existing safety gate).

    Spoken             a str subclass. Only two functions make one:
      from_gate(s)       a sentence the brain's reply_stream yielded (santa/speech.py Gate output, or spec.FALLBACK),
                         after remove-only cleanup for TTS (markdown, asterisks, emoji -> spaces);
      canned(text)       a fixed line that passes speech.sanitize_ex unchanged (the same rule checks as model output).
    assert_speakable   TTS calls this on every line. It refuses anything that is not Spoken, and, as a tripwire,
                       anything spec.safety_reason flags. It never rewrites text.

No rule lives here: santa/spec.py stays the only rules file.
"""
import re

from santa import spec, speech


class Spoken(str):
    """Text approved for TTS. Do not construct directly; use from_gate() or canned()."""
    __slots__ = ("source",)


class UnsafeForTTS(RuntimeError):
    pass


tripwire_hits = 0   # counts lines refused by assert_speakable (should stay 0)

# Remove-only cleanup before TTS: markdown symbols and emoji become spaces (spec.clean already removes most of them;
# this catches anything left). Replacing with a space never joins two words into a new one.
_MARK_RE = re.compile(r"[*_#`~>|\[\]{}<]+")
_SPACE_RE = re.compile(r"\s+")


def tts_text(sentence: str) -> str:
    t = _MARK_RE.sub(" ", sentence)
    t = spec._EMOJI_RE.sub(" ", t)
    t = spec._JOINERS_RE.sub("", t)
    t = _SPACE_RE.sub(" ", t).strip()
    return t if any(ch.isalnum() for ch in t) else ""


def from_gate(sentence: str) -> Spoken | None:
    t = tts_text(sentence)
    if not t:
        return None
    s = Spoken(t)
    s.source = "gate"
    return s


def canned(text: str) -> Spoken:
    heard, why = speech.sanitize_ex(text)
    if why is not None or heard != text:
        raise UnsafeForTTS(f"canned line fails the rule checks ({why}): {text!r} -> {heard!r}")
    if tts_text(text) != text:
        raise UnsafeForTTS(f"canned line has characters TTS cleanup would remove: {text!r}")
    s = Spoken(text)
    s.source = "canned"
    return s


def assert_speakable(line) -> str:
    global tripwire_hits
    if not isinstance(line, Spoken):
        tripwire_hits += 1
        raise UnsafeForTTS("text reached TTS without passing the gate")
    if spec.safety_reason(str(line)) is not None:
        tripwire_hits += 1
        raise UnsafeForTTS(f"tripwire: {spec.safety_reason(str(line))}")
    return str(line)
