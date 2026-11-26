"""Gift question (2026-11-10, Don's request): if gifts have not come up by a child's 5th turn, Santa gently asks one
Christmas-wish question ("What would you like for Christmas?"). Asked once; if the reply did not get to it (for example
the child was sad and Santa comforted instead), it is tried on up to MAX_TRIES - 1 more turns, then dropped.

"Gifts came up" = gift words in the child's words (CHILD_GIFT_WORDS, broad: "I want", "bring me", ...) or in Santa's
spoken reply (SANTA_GIFT_WORDS, narrow: gift, present, wish, Christmas list), on any turn so far; and on a note turn,
any question from Santa that mentions Christmas counts as asked. Never while the child sounds sad: the note is skipped
on a sad turn and on the child's next SAD_COOLDOWN turns (live check: Santa asked right after "I miss him").
Each child (and the unnamed guest) is tracked separately, for this conversation only (a new Santa = a new Call).

Pure logic: no I/O, no model. Santa.build_messages() asks note(name, child_text) for the CURRENT user turn only; reply_stream()
calls advance(name, child_text, spoken) once per turn, only when something was actually spoken (never on FALLBACK).
SANTA_GIFT_ASK=0 turns it off. It is also off when the full Stage I arc (SANTA_ARC=1) is on, which has its own ask.
"""
import os
import re
from dataclasses import dataclass

from . import persona
from .cues import sounds_sad

ASK_AT_TURN = int(os.getenv("SANTA_GIFT_ASK_TURN", "5"))   # the child's turn number that first gets the note
MAX_TRIES = 3                                              # note turns at most (sad turns do not count)
SAD_COOLDOWN = 2                                           # turns without the note after a sad turn

CHILD_GIFT_WORDS = re.compile(
    r"\b(gifts?|presents?|wish(es|ed|ing)?|wishlist|christmas list|stocking"
    r"|(want|wants|wanted|like|hope|hoping|asking|get|getting)( to get)? for christmas|bring me|i want|i wanna"
    r"|i'd like)\b", re.I)
SANTA_GIFT_WORDS = re.compile(
    r"\b(gifts?|presents?|wish(es|ed|ing)?|wishlist|christmas list|bring you"
    r"|(like|want|wants|hope|hoping)\b[^.?!]{0,25}\bfor (this )?christmas)\b", re.I)
GUEST = "the child"


def enabled() -> bool:
    from . import arc
    return os.getenv("SANTA_GIFT_ASK", "1").strip() != "0" and not arc.enabled()


def _norm(text) -> str:
    return str(text).replace("’", "'")


def talks_gifts(text: str) -> bool:
    """The child's words mention gifts or a wish."""
    return CHILD_GIFT_WORDS.search(_norm(text)) is not None


def santa_talks_gifts(reply: str) -> bool:
    return SANTA_GIFT_WORDS.search(_norm(reply)) is not None


def asked_christmas(reply: str) -> bool:
    return "?" in reply and re.search(r"christmas", reply, re.I) is not None


@dataclass
class ChildGifts:
    turns: int = 0          # this child's spoken turns so far
    covered: bool = False   # gifts came up (child or Santa)
    tries: int = 0          # turns that carried the note
    calm_in: int = 0        # turns left before the note may come back after a sad turn


class Gifts:
    def __init__(self):
        self.kids: dict[str, ChildGifts] = {}

    @staticmethod
    def _key(name: str | None) -> str:
        return str(name).casefold() if name else ""

    def state(self, name: str | None) -> ChildGifts:
        return self.kids.get(self._key(name)) or ChildGifts()

    def due(self, name: str | None, child_text: str = "") -> bool:
        """Does this child's turn (saying child_text) get the note? Pure."""
        st = self.state(name)
        return (not st.covered and st.turns + 1 >= ASK_AT_TURN and st.tries < MAX_TRIES and st.calm_in == 0
                and not sounds_sad(child_text))

    def note(self, name: str | None, child_text: str = "") -> str:
        return persona.gift_note(name or GUEST) if self.due(name, child_text) else ""

    def advance(self, name: str | None, child_text: str, spoken: str, held: bool = False) -> bool:
        """Record one spoken turn. Returns whether that turn carried the note. `held`: the note was due but not sent
        (the guide's hello turn), so it is not counted as a try."""
        had = self.due(name, child_text) and not held
        st = self.kids.setdefault(self._key(name), ChildGifts())
        st.turns += 1
        st.tries += had
        if sounds_sad(child_text):
            st.calm_in = SAD_COOLDOWN
        elif st.calm_in:
            st.calm_in -= 1
        if talks_gifts(child_text) or santa_talks_gifts(spoken) or (had and asked_christmas(spoken)):
            st.covered = True
        return had
