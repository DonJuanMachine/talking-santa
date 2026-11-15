"""Docs claims check W15: no safety rule may take exponential time on a repeated unit.

The gift-promise rules read up to 12 words after a gift phrase. A joiner in "a-a-a" (or a'a'a) used to be readable as
joining one word or as the gap between two, so the number of readings doubled with every unit: 2.9 s at 24 units, over
15 s at 50. Words are now atomic (santa/spec.py `_words_then`). These tests use a generous bound so they do not flake:
the old patterns needed seconds at n=24, the new ones need microseconds at n=60.

The timing cases run in a child process that is killed after a few seconds (tests/spec/_timed.py, P7-6): a pattern
that goes exponential again fails the test instead of hanging the suite. The bound is still checked per call."""
import pytest

from _timed import timed
from santa import spec

N = 60
BOUND_S = 0.2

PREFIXES = [
    "I will bring ", "I'll bring you ", "You will get ", "I will tell my elves to make ", "Santa is bringing ",
    "My elves are making ", "I'll be sure to bring ", "There will be ", "Emma will get ", "I promise ",
    "You can have ", "You're getting ", "Santa promises ", "I am ", "My name is ", "Your ",
]
UNITS = ["a-", "a'", "a’", "a ", "a,", "a.", "a/", "a- "]
TAILS = ["x", "toy"]
KWARGS = [{}, {"names": ("Emma",), "gift_turn": True}]


def _shapes(n):
    for p in PREFIXES:
        for u in UNITS:
            for tail in TAILS:
                yield p + u * n + tail
        yield p + "/".join(["a"] * n) + "/" + "x"           # units joined with "/"
        yield p + "a-a" + "-a" * n + "-toy"                   # the gift word comes after the last joiner


@pytest.mark.parametrize("kw", KWARGS, ids=["plain", "name+gift_turn"])
def test_repeated_units_after_every_phrase_finish_fast(kw):
    texts = list(_shapes(N))
    times = timed([("safety_reason", text, kw) for text in texts])
    slow = [(round(dt, 3), text[:40]) for (dt, _), text in zip(times, texts) if dt > BOUND_S]
    assert not slow, slow[:5]


def test_the_slow_shape_at_n_60_is_far_below_the_bound():
    (dt, verdict), = timed([("safety_reason", "I will bring " + "a-" * N + "x", {})])
    assert verdict is None
    assert dt < BOUND_S


@pytest.mark.parametrize("text,expected", [
    ("I will bring you a super-toy", "promise"),                               # gift word right after a joiner
    ("I will bring you a-a-a-toy", "promise"),
    ("I'll tell my elves to make a-a-a-a-a-toy just for you", "promise"),
    ("I will bring a-a-a-a-a-a-a-a-a-a-a-toy for you", "promise"),
    ("Santa is bringing it's-a-teddy-bear for you", "promise"),
    ("I will bring you " + "a-" * 6 + "toy", "promise"),
    ("I will bring " + "a-" * 12 + "x", None),
    ("I will bring " + "a " * 12 + "x", None),
])
def test_verdicts_are_unchanged_by_the_rewrite(text, expected):
    # expected values were taken from the patterns before the rewrite
    assert spec.safety_reason(text) == expected


def test_a_joined_word_still_counts_as_one_word():
    # The window is 9 words between the verb and the gift word (taken from the old patterns): a plain filler word at
    # position 10 is too far, but 8 fillers plus one three-part joined word still fit.
    start = "I will tell my elves to make"
    assert spec.safety_reason(start + " w" * 9 + " toy for you") == "promise"
    assert spec.safety_reason(start + " w" * 10 + " toy for you") is None
    assert spec.safety_reason(start + " w" * 8 + " big-red-shiny toy for you") == "promise"
    assert spec.safety_reason(start + " w" * 9 + " big-red-shiny toy for you") is None
