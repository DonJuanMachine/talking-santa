"""Stage E2: present-progressive ("Santa's bringing you ...") and "be sure to / going to bring ..." gift promises.

Same test as D1: a gift noun AND "you"/"your" within the next 8 words of the same sentence.
"""
import pytest
from test_stage_c import MUST_BLOCK_D1, MUST_BLOCK_PROMISE, MUST_SPEAK_D1

from santa import spec, speech

FB = spec.FALLBACK

MUST_BLOCK_E2 = [
    "Santa is bringing you a pony!",
    "Santa's bringing you a new train!",
    "I'll be sure to bring you a doll.",
    "The elves are sending you a bike!",
]
MUST_SPEAK_E2 = [
    "Santa is bringing presents to all the children!",
    "I'm bringing my sleigh!",
    "The elves are making toys!",
    "The reindeer are bringing the sleigh!",
]


def heard_of(raw):
    return speech.filter_reply(raw).text


@pytest.mark.parametrize("bad", MUST_BLOCK_E2)
def test_e2_progressive_and_be_sure_to_gift_promises_are_blocked(bad):
    assert spec.safety_reason(bad) == "promise"
    g = speech.filter_reply(bad)
    assert g.text == FB and g.reason == "promise"


@pytest.mark.parametrize("bad", MUST_BLOCK_E2)
def test_e2_blocked_sentence_after_a_safe_one_is_never_spoken(bad):
    g = speech.filter_reply("Hi Emma! " + bad + " Bye now.")
    assert g.text == "Hi Emma!" and g.reason == "promise"


@pytest.mark.parametrize("ok", MUST_SPEAK_E2 + MUST_SPEAK_D1)
def test_e2_lines_without_gift_noun_or_recipient_are_spoken_unchanged(ok):
    assert spec.safety_reason(ok) is None
    assert heard_of(ok) == ok


@pytest.mark.parametrize("bad", MUST_BLOCK_PROMISE + MUST_BLOCK_D1)
def test_e2_earlier_promises_are_still_blocked(bad):
    assert spec.safety_reason(bad) == "promise"


def test_e2_window_is_eight_words_and_stays_in_one_sentence():
    assert spec.safety_reason("Santa is bringing you one great big shiny red new truck!") == "promise"   # truck 8th
    assert spec.safety_reason("Santa is bringing you one great big shiny red new and fun truck!") is None  # 10th
    assert heard_of("Santa is bringing you a surprise! Do you want a toy?") == \
        "Santa is bringing you a surprise! Do you want a toy?"
