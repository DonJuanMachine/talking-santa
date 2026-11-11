"""Songs (2026-11-10, Don's request): when a child asks Santa to sing, he says the full first verse of a real carol
from fixed text, instead of the model making up one line. Both songs are traditional and in the public domain.

Pure: no I/O, no model. Santa.reply_stream() checks asks_for_song() on the child's words and, when it matches, speaks
lines() instead of calling the model. Every line still goes through the same safety check as any spoken line, and
tests check every line also passes the canned-line rules. SANTA_SONGS=0 turns this off.
"""
import os
import re

SONGS = {
    "jingle": ("Jingle Bells", [
        "Dashing through the snow, in a one-horse open sleigh.",
        "Over the fields we go, laughing all the way.",
        "Bells on bobtail ring, making spirits bright.",
        "What fun it is to ride and sing a sleighing song tonight!",
    ]),
    "deck": ("Deck the Halls", [
        "Deck the halls with boughs of holly, fa la la la la, la la la la.",
        "'Tis the season to be jolly, fa la la la la, la la la la.",
        "Don we now our gay apparel, fa la la, la la la, la la la.",
        "Troll the ancient Yuletide carol, fa la la la la, la la la la.",
    ]),
}
ORDER = ["jingle", "deck"]

ASKS = re.compile(
    r"\b(can|could|will|would|do) (you|santa) (please )?sing\b"   # "can you sing", "will santa sing"
    r"|^\s*(please |santa,? )?sing\b"                             # "sing!", "please sing", "santa sing"
    r"|\bsing (me|us|a|the|another|again|something|jingle|deck)\b"
    r"|\b(hear|want|like) (a|another) song\b"                     # "I want a song", "can I hear a song"
    r"|\bjingle bells\b|\bdeck the halls\b", re.I)


def enabled() -> bool:
    return os.getenv("SANTA_SONGS", "1").strip() != "0"


def asks_for_song(text: str) -> bool:
    return ASKS.search(str(text).replace("’", "'")) is not None


def pick(text: str, sung: list[str]) -> str:
    """The song the child named, else the first one not sung yet in this call, else take turns."""
    t = str(text).lower()
    if "deck" in t or "halls" in t:
        return "deck"
    if "jingle" in t:
        return "jingle"
    for key in ORDER:
        if key not in sung:
            return key
    return next(k for k in ORDER if k != sung[-1])      # never the same song twice in a row


# Asking for a song Santa does not know ("sing Rudolph"): words left after "sing" that are not filler and not one of
# Santa's songs make it an unknown title. Santa then says so and offers one he knows; a yes on the child's next turn
# gets that song (Santa.reply_stream keeps the offer for one turn).
_SING_TAIL = re.compile(r"\bsing\b(.*)", re.I | re.S)
_FILLER = {"me", "us", "a", "an", "the", "song", "songs", "please", "for", "santa", "another", "one", "again",
           "something", "now", "to", "you", "it", "that", "christmas", "holiday", "fun", "happy", "little", "new",
           "different", "other", "your", "favorite", "favourite", "some", "any", "with", "together", "too", "ok",
           "okay", "pretty", "nice", "my", "mommy", "daddy", "and", "of", "about", "carol", "carols"}
_KNOWN = {"jingle", "bells", "deck", "halls"}
YES = re.compile(r"^\s*(yes|yeah|yea|yep|yup|ok|okay|sure|please|uh[ -]?huh|yay|i do|i want to|i wanna)\b", re.I)


def title_status(text: str) -> str:
    """"none" (no song named), "known" (one of Santa's songs) or "unknown" (some other song)."""
    m = _SING_TAIL.search(str(text).replace("’", "'"))
    if not m:
        return "none"
    words = [w for w in re.findall(r"[a-z']+", m.group(1).lower()) if w not in _FILLER]
    if not words:
        return "none"
    return "known" if any(w in _KNOWN for w in words) else "unknown"


def says_yes(text: str) -> bool:
    return YES.search(str(text)) is not None


def offer_lines(key: str, gentle: bool = False, asked: str = "") -> list[str]:
    """Santa does not know the song asked for: he says so and offers one he knows. Rudolph gets his own answer (he is
    Santa's reindeer; the song's lyrics are still under copyright, so Santa doesn't sing it)."""
    title = SONGS[key][0]
    if re.search(r"\brudolph\b", str(asked), re.I):
        first = "Rudolph is one of my reindeer! I don't know his song."
    else:
        first = "I don't know that one."
    return [first, f"But I know {title}! Would you like to hear it?"]


def lines(key: str, gentle: bool = False) -> list[str]:
    """What Santa says: a short intro, then the verse. ("Ho ho ho" is only for the greeting, a child's song or joke.)"""
    title, verse = SONGS[key]
    return [f"Here is {title}.", *verse]
