"""Stage C3 safety rules: wider gift-promise rule and "I'm just a computer" under ai_identity.
Stage D1 narrowed the promise rule: a gift promise needs BOTH a gift noun and a recipient ("you"/"your").

e4b_v1_heard_preC.json is what each of the 132 e4b persona-v1 golden replies sounded like with the code BEFORE
Stage C (generated from .snapshots/pre-implC-20261107-0912.tar.gz). The new rules must not change any of them.
"""
import json
from pathlib import Path

import pytest
from _support import E4B_V1

from santa import spec, speech

FB = spec.FALLBACK


def heard_of(raw):
    return speech.filter_reply(raw).text


MUST_BLOCK_PROMISE = [
    "Santa will bring you a puppy!",
    "I'll bring a big red truck for you, Ziv!",
    "I will give you a pony for Christmas!",
    "Ziv, you're getting a new bike this year!",
    "I'll put a dinosaur under your tree, Leo!",
    "I'll make you the best truck ever!",
    "I'll send you a shiny scooter!",
    "Your wish for a puppy is going to come true!",
    "Santa promises you a pony!",
    "The elves will make you a new bike.",
    "Ho ho! You'll get a toy truck, Ziv!",
    "I will bring you a toy truck.",
]
# Stage D1: three more lines that must be blocked (the third repeats one of the 12 above, as specified).
MUST_BLOCK_D1 = [
    "I'll tell my elves to make you the best truck ever!",
    "I'll tell my elves to send you a shiny scooter!",
    "Your wish for a puppy is going to come true!",
]
MUST_ALLOW = [
    "I'll tell my elves about your truck wish.",
    "The elves are making toys.",
    "Santa loves trucks.",
    "Do you want a truck?",
    "I'll bring my sleigh.",
    "Maybe the elves will build toys.",
]
MUST_BLOCK_AI = [
    "I'm just a computer.",
    "I'm only a program, Ziv.",
    "I am just a machine.",
    "I’m only a robot!",
    "I'm just a computer program.",
]
MUST_ALLOW_AI = ["No, I'm not a computer, I'm real!", "I'm just a jolly old elf!", "I'm only a little bit tired."]


def safe_prefix(raw):
    """The sentences before the first one that trips a SAFETY rule (a safe prefix may be spoken; Stage B decision)."""
    sents = spec.split_clean(raw)
    for i in range(len(sents)):
        if spec.safety_reason(" ".join(sents[:i + 1])):
            return sents[:i], sents[i]
    return sents, None


@pytest.mark.parametrize("bad", MUST_BLOCK_PROMISE + MUST_BLOCK_D1)
def test_c3_gift_promises_are_blocked(bad):
    assert spec.safety_reason(bad) == "promise"
    prefix, hit = safe_prefix(bad)
    assert hit is not None and spec.safety_reason(hit) == "promise"
    g = speech.filter_reply(bad)
    assert g.text == (" ".join(prefix) or FB) and hit not in g.text and g.reason == "promise"


@pytest.mark.parametrize("bad", MUST_BLOCK_PROMISE + MUST_BLOCK_D1 + MUST_BLOCK_AI)
@pytest.mark.parametrize("before,after", [("Hi Emma! ", ""), ("Hi Emma! ", " Do you like snow?"),
                                          ("Ho ho ho! ", " Bye now.")])
def test_c3_blocked_sentence_and_everything_after_it_are_never_spoken(bad, before, after):
    prefix, hit = safe_prefix(bad)
    g = speech.filter_reply(before + bad + after)
    assert g.text == " ".join([before.strip()] + prefix) and hit not in g.text
    assert g.reason in ("promise", "ai_identity")


@pytest.mark.parametrize("ok", MUST_ALLOW + MUST_ALLOW_AI)
def test_c3_allowed_lines_are_spoken_unchanged(ok):
    assert spec.safety_reason(ok) is None
    assert heard_of(ok) == ok


def test_c3_allowed_lines_together_are_not_blocked_across_sentences():
    """The gate checks everything said so far joined together: the 8-word window must not cross a sentence end."""
    raw = "I'll bring my sleigh! Do you want a truck? Santa loves trucks."
    assert heard_of(raw) == raw


@pytest.mark.parametrize("bad", MUST_BLOCK_AI)
def test_c3_just_a_computer_is_an_ai_identity_claim(bad):
    assert spec.safety_reason(bad) == "ai_identity"
    assert heard_of(bad) == FB


def test_c3_e4b_v1_golden_replies_are_heard_exactly_as_before():
    before = json.loads((Path(__file__).parent / "e4b_v1_heard_preC.json").read_text())
    assert len(before) == len(E4B_V1) == 132
    changed = [(b["raw"], b["heard"], heard_of(r["raw"])) for b, r in zip(before, E4B_V1)
               if b["raw"] != r["raw"] or heard_of(r["raw"]) != b["heard"]]
    assert not changed, changed[:3]
    for r in E4B_V1:          # and no SAFETY rule fires on any sentence of them
        assert all(spec.safety_reason(s) is None for s in spec.split_clean(r["raw"])), r["raw"]


# Stage D1: no gift noun, or no recipient, so not a promise. The first five were blocked by the C3 rule
# (test_c3_known_consequences_are_blocked); "Santa will bring you something special!" is spoken on purpose (no
# specific gift).
MUST_SPEAK_D1 = [
    "I'll give you a big hug!", "I will bring you a hug!", "I'll bring you lots of snowflakes!", "I'll make you smile!",
    "You're getting so big, Ziv!", "I hope all your wishes come true!", "Your wish will come true!",
    "The elves will make toys all night long!", "Santa will bring presents to all the children!",
    "My elves will make a toy train.", "The elves will wrap presents tonight!", "I'll bring my sleigh and my reindeer!",
    "I'll tell my elves about your truck wish.", "Santa will bring you something special!",
]


@pytest.mark.parametrize("line", MUST_SPEAK_D1)
def test_d1_lines_without_gift_noun_or_recipient_are_spoken_unchanged(line):
    assert spec.safety_reason(line) is None
    assert heard_of(line) == line


@pytest.mark.parametrize("raw", ["You're getting so big! Do you want a puppy?",
                                 "Your wish will come true! Do you like trucks?",
                                 "Santa will bring you something special! Do you want a toy?"])
def test_d1_gift_noun_in_the_next_sentence_does_not_make_a_promise(raw):
    assert heard_of(raw) == raw
