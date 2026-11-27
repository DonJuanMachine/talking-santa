"""Conversation guide (2026-11-25, Don's request; conversation starters 2026-11-27). For each child, per call:

  HELLO       the child's first answered turn: Santa says hello by name, tells a child who called before that he is
              happy to hear from them again, and asks how they are (nothing else).
  starters    after the hello, when the child has gone QUIET_TURNS turns in a row without asking Santa a question,
              Santa opens the next starter not used yet this call, in this order:
    KINDNESS  "Have you done something kind or nice for someone today?"; the child's next turn gets KIND_REPLY: how
              kind that was, or "That's okay! You could give Nana a big hug today." (someone from the child's family
              list, rotating from call to call; "someone who needs it" without one). Never the nice or naughty list.
    LIKES     ONE question about something the child likes. If the profile has a remembered like or pet ("likes snow
              angels", "has a cat named Mittens"), about that one; which one rotates from call to call (from day to day
              without the call log). Wishes ("wants a drawing pad") are never used: asking about a wish invites a
              promise.
    GIFT      the Christmas wish question (persona.gift_note), only if gifts have not come up (santa/gifts.py decides).
  Each starter is tried on at most STARTER_TRIES turns, and is done once Santa asks it. A turn where the child is sad
  (or was a moment ago), raises a topic Santa answers with care, or tells of a loss gets no starter and resets the
  count: the child led there (brain.py decides).
  WRAP        a slow wrap-up (Don, 2026-11-27): after WRAP_AFTER answers in a row with no question to Santa, "If you
              don't have any questions for Santa, you can go and enjoy your day, but I'm happy to talk more! Would you
              like to talk some more?" The child's next turn gets WRAP_REPLY: if they want to talk more, the Christmas
              wish (if never asked), else a remembered like not asked yet this call, else what they like to play; if
              not, a warm goodbye. The count starts again after it, so it can come again after WRAP_AFTER more.
  AFTER_BYE   once Santa said that goodbye, the child's next turns (until they ask something, or the wrap-up comes
              again) get: answer warmly in a few words, start nothing new. Live, a goodbye followed by the child's
              "ok" got a whole new question ("Do you like to make big snow angels?").

A guest (a child who is not registered) gets all of it too; all guests share one slot (name None), as in the gift
question. Before the starters, a guest got the hello only.

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
from dataclasses import dataclass, field

HELLO, KINDNESS, KIND_REPLY, LIKES, GIFT = "hello", "kindness", "kind_reply", "likes", "gift"
WRAP, WRAP_REPLY, AFTER_BYE = "wrap", "wrap_reply", "after_bye"
STARTERS = (KINDNESS, LIKES, GIFT)   # in this order, each at most once per call
QUIET_TURNS = 2              # the child's turns in a row without a question to Santa before a starter
STARTER_TRIES = 2            # turns a starter's (or the wrap-up's) note is sent at most; done early once Santa asks
WRAP_AFTER = 7               # the child's answers in a row without a question to Santa before the wrap-up

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


# Did Santa ask the likes question? A question sentence about liking or playing, or one that names the remembered thing.
# Any "?" used to count, so "Was it cold outside?" ended the likes question for the call (review 2026-11-25).
_QUESTION = re.compile(r"[^.!?]*\?")
_LIKE_WORDS = re.compile(r"\b(like|likes|love|loves|favou?rite|play|playing|enjoy|fun)\b", re.I)
_FACT_STOP = {"likes", "loves", "enjoys", "favorite", "favourite", "has", "have", "named", "called", "with", "and",
              "the", "pet", "pets", "two", "three", "very", "much", "lots", "playing", "play"}


def _fact_words(fact: str | None) -> set:
    return {w for w in re.findall(r"[a-z']+", (fact or "").lower()) if len(w) > 2 and w not in _FACT_STOP}


def asked_about_likes(spoken: str, fact: str | None = None) -> bool:
    """True if one of Santa's questions is about what the child likes, or names a word of `fact` ("snow angels",
    "Mittens")."""
    words = _fact_words(fact)
    for q in _QUESTION.findall(spoken or ""):
        if _LIKE_WORDS.search(q) or words & set(re.findall(r"[a-z']+", q.lower())):
            return True
    return False


def asked_fact(spoken: str, fact: str | None) -> bool:
    """True if one of Santa's questions names a word of `fact` (only the fact, not any likes question)."""
    words = _fact_words(fact)
    return bool(words) and any(words & set(re.findall(r"[a-z']+", q.lower())) for q in _QUESTION.findall(spoken or ""))


# Did Santa ask the kindness question? A question sentence about being kind, nice, helping or sharing.
_KIND_WORDS = re.compile(r"\b(kind|kindness|nice|help|helped|helping|share|shared|sharing|good deed)\b", re.I)


def asked_kindness(spoken: str) -> bool:
    return any(_KIND_WORDS.search(q) for q in _QUESTION.findall(spoken or ""))


# Did Santa ask whether the child wants to talk more?
_TALK_MORE = re.compile(r"\b(talk|talking|chat|chatting)\b", re.I)


def asked_wrap(spoken: str) -> bool:
    return any(_TALK_MORE.search(q) for q in _QUESTION.findall(spoken or ""))


def asked_starter(starter: str, spoken: str, fact: str | None = None) -> bool:
    """Did Santa's reply ask the starter its note carried?"""
    if starter == KINDNESS:
        return asked_kindness(spoken)
    if starter == LIKES:
        return asked_about_likes(spoken, fact)
    return "?" in (spoken or "") and re.search(r"christmas", spoken or "", re.I) is not None   # GIFT


# Who the child could give a hug to, from the profile's family list ({"mom": "Mommy", "grandmother": ["Nana", ...]}):
# what the child calls them, one per relation (the first name listed). For the KIND_REPLY note.
def family_names(profile) -> list[str]:
    fam = profile.get("family") if isinstance(profile, dict) else None
    out = []
    for names in (fam.values() if isinstance(fam, dict) else []):
        names = [names] if isinstance(names, str) else list(names or [])
        first = next((" ".join(str(n).split()) for n in names if str(n).strip()), "")
        if first and first not in out:
            out.append(first)
    return out


def pick_family(profile, seed: int) -> str | None:
    """One family member's name to suggest a hug for, rotating with `seed` (as pick_fact), or None."""
    names = family_names(profile)
    return names[seed % len(names)] if names else None


def like_facts(facts) -> list[str]:
    """The child's remembered likes and pets, newest first."""
    out = []
    for f in reversed(list(facts or [])):
        f = " ".join(str(f).split())
        if f and _LIKE_FACT.match(f) and not _WISH.search(f):
            out.append(f)
    return out


def pick_fact(facts, seed: int, skip=()) -> str | None:
    """One like or pet to ask about, or None. `seed` (Santa._like_seed: the number of earlier calls, or the date) rotates
    the pick, so a child who calls every day is not asked about the same thing each time. `skip`: already asked."""
    likes = [f for f in like_facts(facts) if f not in skip]
    return likes[seed % len(likes)] if likes else None


@dataclass
class ChildGuide:
    hello_done: bool = False
    quiet: int = 0                                    # the child's turns in a row without a question to Santa
    done: set = field(default_factory=set)            # starters Santa asked this call
    tries: dict = field(default_factory=dict)         # starter -> turns its note was sent
    kind_asked: bool = False                          # Santa just asked KINDNESS: the next turn gets KIND_REPLY
    answers: int = 0                                  # the child's answers in a row without a question (WRAP_AFTER)
    wrap_tries: int = 0                               # WRAP notes sent since the count last started
    wrap_asked: bool = False                          # Santa just offered the wrap-up: the next turn gets WRAP_REPLY
    facts_asked: set = field(default_factory=set)     # remembered likes Santa asked about this call
    said_bye: bool = False                            # Santa said goodbye after the wrap-up (AFTER_BYE)


class Guide:
    """Guide state for one conversation (a fresh Santa = a fresh Call)."""

    def __init__(self):
        self.kids: dict[str, ChildGuide] = {}

    @staticmethod
    def _key(name: str | None) -> str:
        return "" if name is None else str(name).casefold()     # "": the guest slot (registered names are never empty)

    def state(self, name: str | None) -> ChildGuide:
        return self.kids.get(self._key(name)) or ChildGuide()

    def kind(self, name: str | None, gentle: bool = False, led: bool = False, gift_open: bool = True) -> str | None:
        """Which note this child's NEXT turn gets (None = none). Pure. `name` None is the guest slot.
        `gentle`: the child is sad now or was a moment ago, raised a topic Santa answers with care, or told of a loss;
        the hello still comes (its safety suffix says comfort first), starters and KIND_REPLY wait.
        `led`: this turn the child asked Santa a question (or `gentle`): it does not count as quiet.
        `gift_open`: the Christmas wish may still be asked (gifts have not come up; santa/gifts.py)."""
        st = self.state(name)
        if not st.hello_done:
            return HELLO
        if gentle:
            return None
        if st.kind_asked:
            return KIND_REPLY
        if st.wrap_asked:
            return WRAP_REPLY
        if led:
            return None
        if st.answers + 1 >= WRAP_AFTER and st.wrap_tries < STARTER_TRIES:
            return WRAP
        if st.said_bye:
            return AFTER_BYE
        if st.quiet + 1 < QUIET_TURNS:
            return None
        return next((s for s in STARTERS if s not in st.done and st.tries.get(s, 0) < STARTER_TRIES
                     and (s != GIFT or gift_open)), None)

    def advance(self, name: str | None, spoken: str, sent: str | None, fact: str | None = None,
                led: bool = False, pick: str | None = None) -> None:
        """Record one spoken turn of `name` (None: a guest) that carried note `sent` (None: no guide note, e.g. a
        song). `fact`: the remembered like that a LIKES or WRAP_REPLY note asked about, if any. `led`: as in kind().
        `pick`: the remembered like the LIKES starter would ask about. If Santa asks about it on his own, the starter is
        done (live: "Do you like to make snow angels?" on turn 2 by himself, then again from the starter, 4 of 4)."""
        st = self.kids.setdefault(self._key(name), ChildGuide())
        if pick and sent != HELLO and asked_fact(spoken, pick):
            st.facts_asked.add(pick)
            st.done.add(LIKES)
        st.kind_asked = st.wrap_asked = False
        if sent == HELLO:
            st.hello_done = True
            return
        st.quiet = 0 if led else st.quiet + 1
        st.answers = 0 if led else st.answers + 1
        if led:
            st.said_bye = False                       # the child asked something: talking again
        if st.answers == 0:
            st.wrap_tries = 0
        if fact and sent in (LIKES, WRAP_REPLY) and asked_about_likes(spoken, fact):
            st.facts_asked.add(fact)
        if sent == WRAP:
            st.wrap_tries += 1
            if asked_wrap(spoken):
                st.wrap_asked = True
                st.answers = st.wrap_tries = 0        # it may come again after WRAP_AFTER more answers
        elif sent == WRAP_REPLY:
            st.said_bye = "?" not in (spoken or "")   # no question back: Santa said goodbye
            if asked_starter(GIFT, spoken):
                st.done.add(GIFT)
        if sent in STARTERS:
            st.tries[sent] = st.tries.get(sent, 0) + 1
            if asked_starter(sent, spoken, fact):
                st.done.add(sent)
                st.quiet = 0                           # the child's answer starts the count again
                st.kind_asked = sent == KINDNESS
