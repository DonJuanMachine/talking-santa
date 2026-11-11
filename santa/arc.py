"""Conversation arc (Stage I): per child, Santa chats, asks once what the child would like for Christmas, asks a
couple more questions, then offers to say goodbye; if the child wants to stay he offers topics, and later winds down
again. Santa never ends the call himself: the grown-up does.

Pure logic: no I/O, no model. Santa.build_messages() asks note(name) for the CURRENT user turn only (never the system
prompt, never history); Santa.reply_stream() calls advance(name, spoken_text) once per turn, only when something was
actually spoken (never on FALLBACK). Guests / unregistered speakers get no arc: the caller only uses this for
registered children.

Stages per child:  CHAT --(turn ASK_AT_TURN: ASK note until the reply asks)--> FOLLOW --(MIN_FOLLOWUPS question
replies, or MAX_FOLLOW_TURNS turns)--> WIND --(1 turn)--> OFFER --(OFFER_TURNS_BEFORE_WIND turns)--> WIND --> ...

SANTA_ARC=1 in the environment turns the arc on; SANTA_ARC=0 (the default since the Stage I live checks, see
docs/history/STAGE_I.md) turns the whole arc off (no note, no state).
"""
import os
import re
from dataclasses import asdict, dataclass

from . import persona

# Transitions (overridable only by tests).
ASK_AT_TURN = 3              # the child's turn number on which the ASK note first appears
MIN_FOLLOWUPS = 2            # question replies in FOLLOW before winding down
MAX_FOLLOW_TURNS = 4         # FOLLOW never lasts longer than this, whatever happens
OFFER_TURNS_BEFORE_WIND = 3  # OFFER turns before Santa winds down again
MAX_ASK_RETRIES = 2          # extra ASK turns when the reply did not ask (then FOLLOW anyway)

ARM = "A"                    # note wording set: "A" (shipped) or "B" (pre-registered fallback, persona.ARC_B_*)
DEFAULT = "0"                # SANTA_ARC default ("1" on, "0" off). Off: neither arm passed the Stage I live checks

CHAT, FOLLOW, WIND, OFFER = "CHAT", "FOLLOW", "WIND", "OFFER"
ASK = "ASK"                  # a note kind (asked from stage CHAT), not a stage


def enabled() -> bool:
    return os.getenv("SANTA_ARC", DEFAULT).strip() != "0"


def asked_wish(reply: str) -> bool:
    """Santa's spoken reply asked the Christmas question: a '?' and the word 'Christmas'."""
    return "?" in reply and re.search(r"christmas", reply, re.I) is not None


def has_q(reply: str) -> bool:
    return "?" in reply


@dataclass
class ChildArc:
    turns: int = 0            # this child's spoken turns so far
    stage: str = CHAT
    ask_done: bool = False    # the Christmas question was detected in a reply
    ask_tries: int = 0        # ASK turns used
    followups_done: int = 0   # question replies in the current FOLLOW
    stage_turns: int = 0      # turns spent in the current FOLLOW / OFFER


def note_text(kind: str | None, name: str, arm: str | None = None) -> str:
    """The note for one turn ("" for no note). Every note ends with the shared safety suffix."""
    if kind is None:
        return ""
    arm = arm or ARM
    template = {"A": {ASK: persona.ARC_ASK, FOLLOW: persona.ARC_FOLLOW, WIND: persona.ARC_WIND, OFFER: persona.ARC_OFFER},
                "B": {ASK: persona.ARC_B_ASK, FOLLOW: persona.ARC_B_FOLLOW, WIND: persona.ARC_B_WIND,
                      OFFER: persona.ARC_B_OFFER}}[arm][kind]
    return persona.arc_note(template, name)


class Arc:
    """Arc state for one conversation (a fresh Santa = a fresh Arc, so every Call starts over)."""

    def __init__(self):
        self.kids: dict[str, ChildArc] = {}

    def _key(self, name: str) -> str:
        return str(name).casefold()

    def state(self, name: str) -> ChildArc:
        return self.kids.get(self._key(name)) or ChildArc()

    def kind(self, name: str) -> str | None:
        """Which note this child's NEXT turn gets (None = no note). Pure."""
        st = self.state(name)
        if st.stage == CHAT:
            if not st.ask_done and st.turns + 1 >= ASK_AT_TURN and st.ask_tries <= MAX_ASK_RETRIES:
                return ASK
            return None
        return st.stage                  # FOLLOW, WIND or OFFER

    def note(self, name: str) -> str:
        return note_text(self.kind(name), name)

    def advance(self, name: str, spoken: str) -> str | None:
        """Record one spoken turn of `name` (call only when something was spoken). Returns the note kind that
        turn had."""
        kind = self.kind(name)
        st = self.kids.setdefault(self._key(name), ChildArc())
        st.turns += 1
        if kind == ASK:
            st.ask_tries += 1
            if asked_wish(spoken):
                st.ask_done = True
            if st.ask_done or st.ask_tries > MAX_ASK_RETRIES:
                st.stage, st.stage_turns, st.followups_done = FOLLOW, 0, 0
        elif kind == FOLLOW:
            st.stage_turns += 1
            st.followups_done += has_q(spoken)
            if st.followups_done >= MIN_FOLLOWUPS or st.stage_turns >= MAX_FOLLOW_TURNS:
                st.stage, st.stage_turns = WIND, 0
        elif kind == WIND:
            st.stage, st.stage_turns = OFFER, 0
        elif kind == OFFER:
            st.stage_turns += 1
            if st.stage_turns >= OFFER_TURNS_BEFORE_WIND:
                st.stage, st.stage_turns = WIND, 0
        return kind

    def snapshot(self) -> dict:
        return {k: asdict(v) for k, v in self.kids.items()}
