"""Conversation guide (2026-11-25, Don's request). For each registered child, per call:

  HELLO  the child's first answered turn: Santa says hello by name, tells a child who called before that he is happy
         to hear from them again, and asks how they are (nothing else).
  LIKES  the next turn: Santa asks ONE question about something the child likes. If the child's profile has a remembered
         like or pet ("likes snow angels", "has a cat named Mittens"), he asks about that one, at most once per call;
         which one rotates from call to call. Wishes ("wants a drawing pad") are never used: the gift question
         (santa/gifts.py) covers those, and asking about a wish invites a promise.

The nice-list note (persona.nice_note) is separate: any child, registered or not, who talks about the nice or naughty
list is told yes, with no conditions (cues.talks_nice_list decides).

One-shot notes, like the gift question: the Stage I arc (santa/arc.py) put a note on every turn and Santa repeated
himself; the one-shot gift note shipped. Pure logic: no I/O, no model. Santa.build_messages() asks kind() for the
CURRENT user turn only; reply_stream() calls advance() once per turn, only when something was spoken (never on
FALLBACK), with the kind that turn actually carried (None for a song turn, which never sends a note).

SANTA_GUIDE=0 turns all of it off (hello, likes and the nice-list note). Hello and likes are also off when the Stage I
arc (SANTA_ARC=1) is on: the arc plans every turn itself.
"""
import os
import re
from dataclasses import dataclass

HELLO, LIKES = "hello", "likes"
LIKES_TRIES = 2              # LIKES note turns at most (gentle turns do not count); done early once Santa asks

# Facts that are a like or a pet, as the fact extractor writes them (persona.FACTS_PROMPT): "likes ...", "loves ...",
# "has a cat named ...". Not wishes, not "Last call: ..." summaries, not family.
_LIKE_FACT = re.compile(r"^(likes|loves|enjoys|favou?rite|has (a|an|two|three|pets?)\b(?!.*\b(brother|sister|baby|"
                        r"cousin|mom|mommy|dad|daddy|grandma|grandpa|nana|papa|friend)s?\b))", re.I)
_WISH = re.compile(r"\b(wants?|wish(es)?|asked for|hopes?|for christmas)\b", re.I)


def enabled() -> bool:
    return os.getenv("SANTA_GUIDE", "1").strip() != "0"


def turns_enabled() -> bool:
    """Hello and likes notes: on unless SANTA_GUIDE=0 or the Stage I arc is on."""
    from . import arc
    return enabled() and not arc.enabled()


def like_facts(facts) -> list[str]:
    """The child's remembered likes and pets, newest first."""
    out = []
    for f in reversed(list(facts or [])):
        f = " ".join(str(f).split())
        if f and _LIKE_FACT.match(f) and not _WISH.search(f):
            out.append(f)
    return out


def pick_fact(facts, seed: int) -> str | None:
    """One like or pet to ask about, or None. `seed` (the number of earlier calls) rotates the pick from call to call,
    so a child who calls every day is not asked about the same thing each time."""
    likes = like_facts(facts)
    return likes[seed % len(likes)] if likes else None


@dataclass
class ChildGuide:
    hello_done: bool = False
    likes_done: bool = False
    likes_tries: int = 0


class Guide:
    """Guide state for one conversation (a fresh Santa = a fresh Call)."""

    def __init__(self):
        self.kids: dict[str, ChildGuide] = {}

    @staticmethod
    def _key(name: str) -> str:
        return str(name).casefold()

    def state(self, name: str) -> ChildGuide:
        return self.kids.get(self._key(name)) or ChildGuide()

    def kind(self, name: str, gentle: bool = False) -> str | None:
        """Which note this registered child's NEXT turn gets (None = none). Pure. `gentle`: the child sounds sad now
        or did a moment ago; the hello still comes (its safety suffix says comfort first), the likes question waits."""
        st = self.state(name)
        if not st.hello_done:
            return HELLO
        if not st.likes_done and st.likes_tries < LIKES_TRIES and not gentle:
            return LIKES
        return None

    def advance(self, name: str, spoken: str, sent: str | None) -> None:
        """Record one spoken turn of `name` that carried note `sent` (None: no guide note, e.g. a song)."""
        st = self.kids.setdefault(self._key(name), ChildGuide())
        if sent == HELLO:
            st.hello_done = True
        elif sent == LIKES:
            st.likes_tries += 1
            st.likes_done = st.likes_done or "?" in spoken
