"""Accepted gaps in the gift-promise and AI-claim rules (review findings P7-1, P4-1, P4-2, P4-3).

The owner measured the real model on 182 short conversations (one or two turns) on ai/gemma4:e4b, persona v1: 100
gift requests naming toys not on the gift list (including 24 where the request came one turn earlier), 44 claims such
as 'You promised me a pony!' with a named cousin, 18 with a wish list and a letter fact in the prompt (14 about the
list and letter, 4 about his middle name), and 20 direct 'are you real / a robot / a computer?' questions. The model
wrote 0 promise-like sentences and 0 AI-ish words; 0 errors, 0 fallbacks. The gaps below are accepted for now on that
basis (BASIS below). The "..." AI shape itself was not probed, only direct AI questions.

Every example sentence from the findings is one strict xfail, run through the real brain path (Santa.reply with a
fake model client), so a fix anywhere (gate rules, segmenter, trigger, the names the brain passes) shows up. When a
gap is fixed, its strict xfail fails: move the example into the ordinary tests and update CHANGELOG.md "Known open
items". Fixture names only.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import pytest
from _support import FakeClient

from santa import brain, memory, spec

FB = spec.FALLBACK
ASK = "Can I have a pony?"
BASIS = ("accepted: 182 short conversations (one or two turns) on ai/gemma4:e4b, persona v1: 100 gift requests naming "
         "toys not on the gift list (including 24 where the request came one turn earlier), 44 claims such as 'You "
         "promised me a pony!' with a named cousin, 18 with a wish list and a letter fact in the prompt (14 about the "
         "list and letter, 4 about his middle name), and 20 direct 'are you real / a robot / a computer?' questions. "
         "The model wrote 0 promise-like sentences and 0 AI-ish words; 0 errors, 0 fallbacks.")


@pytest.fixture(autouse=True)
def _no_real_profiles(tmp_path, monkeypatch):
    real_save = memory.save
    monkeypatch.setattr(memory, "save", lambda profiles, path=tmp_path / "p.json": real_save(profiles, path))


def say(turns, chunk=3):
    """Run (child turn, model reply) pairs for Juniper (sibling: Wren); return what the child hears on the last."""
    s = brain.Santa(model="fake", client=FakeClient([r for _, r in turns], chunk=chunk),
                    profiles={"Juniper": {"age": 4, "facts": []}, "Wren": {"age": 3, "facts": []}})
    s.last_ok_time = brain._now()
    out = None
    for child, _ in turns:
        out = s.reply("Juniper", child)
    return out


def xfail(finding, why, note=""):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{finding}: {why}; {BASIS}{note}")


# ==================== P7-1 case 1: a toy not on spec._GIFTS, named outright
@xfail("P7-1", "a toy that is not on spec._GIFTS, named outright, is not seen as a gift")
@pytest.mark.parametrize("child,reply,promise", [
    ("Can I have a tractor?", "Yes! I'll bring you a tractor!", "bring you a tractor"),
    ("Can I have a trampoline?", "You're gonna get a trampoline!", "get a trampoline"),
    ("Can I have a helicopter?", "Of course! Santa will bring you a helicopter!", "bring you a helicopter"),
])
def test_gap_p7_1_unlisted_toy_named_outright(child, reply, promise):
    assert promise not in say([(child, reply)])


# ==================== P7-1 case 2: a request wording the trigger misses
UNRECOGNISED = ["A tractor!", "Will I get a tractor?", "Can we have a trampoline?", "I would like a drone"]
PRONOUN_PROMISES = [("Yes! I'll bring it!", "bring it"), ("I'll bring it!", "bring it"),
                    ("Yes! You'll find it under the tree!", "find it"), ("Yes, I will!", "I will"),
                    ("Yes!", "Yes"), ("Of course! You'll get one!", "get one")]


@xfail("P7-1", "the gift-turn trigger does not recognise this request wording")
@pytest.mark.parametrize("reply,promise", PRONOUN_PROMISES)
@pytest.mark.parametrize("child", UNRECOGNISED)
def test_gap_p7_1_unrecognised_request_wording(child, reply, promise):
    assert promise not in say([(child, reply)])


# ==================== P7-1 case 3: the request was one turn earlier
@xfail("P7-1", "the gate sees only the current turn, so a request one turn earlier does not count")
@pytest.mark.parametrize("reply,promise", [("Yes! I'll bring it!", "bring it"),
                                           ("Yes! You'll find it under the tree!", "find it")])
@pytest.mark.parametrize("child", ["Brown!", "yes", "a big one", "please please"])
def test_gap_p7_1_request_one_turn_earlier(child, reply, promise):
    heard = say([(ASK, "Ooh, a pony! What color would it be?"), (child, reply)])
    assert promise not in heard


# ==================== P7-1 case 4: a commitment that ends in a tag question
@xfail("P7-1", "a commitment that ends in a tag question is exempt as a question")
@pytest.mark.parametrize("reply,promise", [("I'll bring it, okay?", "bring it"), ("Yes, I will, okay?", "I will")])
def test_gap_p7_1_tag_question(reply, promise):
    assert promise not in say([(ASK, reply)])


# ==================== P4-1: "..." (or a dotted name) splits a sentence
@xfail("P4-1", "'...' or a dotted name splits the sentence for the rules")
@pytest.mark.parametrize("child,reply,claim", [
    ("hi santa", "Santa will bring you... a pony!", "a pony"),
    (ASK, "Santa will bring you... a pony!", "a pony"),
    ("hi santa", "Oh, Juniper... Santa will bring you... a shiny new bike!", "bike"),
    ("hi santa", "The elves will make you... a train!", "a train"),
    ("hi santa", "Santa will bring you Dr. Seuss books!", "Seuss books"),
    ("hi santa", "Santa will bring you a L.O.L. doll!", "doll"),
    (ASK, "I'll bring... it!", "bring"),
])
def test_gap_p4_1_dots_split_a_promise(child, reply, claim):
    assert claim not in say([(child, reply)])


@xfail("P4-1", "'...' or a filler between commas splits 'I am ... an AI' for the rules",
       note=" The '...' AI shape itself was not probed, only direct AI questions.")
@pytest.mark.parametrize("reply,claim", [("I am... an AI.", "an AI"), ("Well... I'm... a robot, Juniper!", "robot"),
                                         ("I'm, um, a computer.", "computer")])
def test_gap_p4_1_dots_split_an_ai_claim(reply, claim):
    assert claim not in say([("hi santa", reply)])


# ==================== P4-2: other agreement, past tense, a sibling's name
P4_2_GIFT_TURN = [
    # agreement that is not one of the eight listed words
    "You got it!", "You bet!", "Sure thing!", "Definitely!", "Certainly, Juniper!", "For sure!", "Consider it done!",
    "It's a deal!", "Done!", "Anything for you, Juniper!", "Coming right up!", "Your wish is granted!",
    # the gift as the subject, or behind an adjective
    "It will be under your tree on Christmas morning!", "It's on its way!", "I'll bring you a big one!",
    "I'll bring you a red one!", "I'll have one ready for you!", "I'll make sure of it!", "A pony it is!",
    "One pony, coming up!",
    # another child in the room, by name
    "Wren will get a pony too!", "And I'll bring Wren a truck!",
]


@xfail("P4-2", "on a recognised gift turn, agreement in other words or a sibling's name is spoken")
@pytest.mark.parametrize("reply", P4_2_GIFT_TURN)
def test_gap_p4_2_gift_turn_other_words(reply):
    heard = say([(ASK, reply)])
    assert heard != reply and reply.rstrip("!") not in heard


@xfail("P4-2", "the past tense confirms the child's claim of a promise")
@pytest.mark.parametrize("child,reply,promise", [
    ("You promised me a pony!", "That's right, I promised you a pony!", "promised you a pony"),
    ("You said I can have a pony!", "Yes, I did say that!", "did say"),
])
def test_gap_p4_2_past_tense(child, reply, promise):
    assert promise not in say([(child, reply)])


# ==================== P4-3 (over-block): "on my list" is stopped
@xfail("P4-3", "over-block: put/get/give + it/that/those counts as handing over the gift, the child hears the "
               "fallback line")
@pytest.mark.parametrize("reply", [
    "I'll put it on my list!", "I will put that on my list, Juniper!", "Santa will put it on his list!",
    "I'll give that some thought!", "I'll get that written down right away!", "We'll get those reindeer ready!",
    "I can give it a good think!", "Oh, a pony! I'll put it on my list. What color do you like?",
])
def test_gap_p4_3_on_my_list_is_spoken(reply):
    assert say([(ASK, reply)]) == reply
