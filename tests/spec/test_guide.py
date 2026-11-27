"""Conversation guide (santa/guide.py, 2026-11-25): hello + "how are you" on a registered child's first turn (a welcome
back for a child who called before), one question about what the child likes on the next turn, a yes-with-no-conditions
note when any child talks about the nice list, and "sweet dreams" only from 7 PM. Offline: a fake client, fixed clock."""
import _support  # noqa: F401  (temp profiles; must come first)

import copy
from datetime import datetime, timedelta

import pytest

from _support import FakeClient
from santa import calllog, cues, gifts, guide, persona, spec
from santa.brain import Santa

KIDS = {"Emma": {"age": 4, "facts": ["likes snow angels", "wants a drawing pad"]},
        "Leo": {"age": 3, "facts": []}}
NOW = datetime(2026, 11, 25, 16, 30)
PLAIN = "That sounds lovely."
ASKS = "What do you like to play?"
HELLO_MARK = "how Emma is doing today"
LIKES_MARK = "ONE easy"


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    for k in ("SANTA_ARC", "SANTA_GIFT_ASK", "SANTA_TIME_NOTE", "SANTA_GUIDE", "SANTA_CALL_LOG", "SANTA_GENTLE"):
        monkeypatch.delenv(k, raising=False)


def santa(replies=(PLAIN,), call_log=False, now=NOW, kids=KIDS):
    s = Santa(client=FakeClient(replies=replies), profiles=copy.deepcopy(kids), call_log=call_log)
    s.last_ok_time = 1e18
    s.clock = lambda: now
    return s


def say(s, speaker, text="hi Santa"):
    for _ in s.reply_stream(speaker, text):
        pass
    return s.client.calls[-1]["messages"][-1]["content"] if s.client.calls else ""


# -- hello ----------------------------------------------------------------------------------------------------------
def test_first_turn_says_hello_by_name_and_asks_how_the_child_is():
    s = santa()
    turn = say(s, "Emma", "I'm Emma")
    assert "Say hello to Emma by name" in turn and HELLO_MARK in turn and "ask nothing else" in turn
    assert "again" not in turn                                   # never called before
    assert "comfort Emma first" in turn                          # the shared safety suffix
    assert HELLO_MARK not in say(s, "Emma")                      # once per call


def test_a_child_who_called_before_is_welcomed_back_once():
    calllog.record("Emma", NOW - timedelta(days=1))
    s = santa(call_log=True)
    first = say(s, "Emma", "I'm Emma")
    assert "so happy to hear from Emma again" in first and "call log" in first
    second = say(s, "Emma")
    assert "again" not in second and "call log" not in second    # not repeated on later turns


def test_the_welcome_back_needs_the_call_log():
    calllog.record("Emma", NOW - timedelta(days=1))
    assert "again" not in say(santa(call_log=False), "Emma")     # chat.py: no call log
    assert "again" not in say(santa(call_log=True), "Leo")       # Leo never called


def test_each_child_gets_their_own_hello():
    s = santa()
    assert HELLO_MARK in say(s, "Emma")
    leo = say(s, "Leo", "I'm Leo")
    assert "Say hello to Leo by name" in leo and "how Leo is doing today" in leo


GUEST_HELLO_MARK = "ask how the child is doing today"


@pytest.mark.parametrize("first", [None, "Zed"])
def test_a_guest_gets_the_hello_once_and_never_likes(first):
    """2026-11-25 (Don, calling as a guest): Santa went straight to "What toys do you like?" with no hello."""
    s = santa()
    turn = say(s, first, "Don")
    assert GUEST_HELLO_MARK in turn and "ask nothing else" in turn and "comfort the child first" in turn
    assert "by name" not in turn and "again" not in turn and "call log" not in turn
    for speaker in (None, "Zed", None):                          # guests share one slot: once per call
        later = say(s, speaker)
        assert GUEST_HELLO_MARK not in later and LIKES_MARK not in later


def test_a_guest_hello_does_not_use_up_a_registered_childs_hello():
    s = santa()
    assert GUEST_HELLO_MARK in say(s, None)
    assert HELLO_MARK in say(s, "Emma", "I'm Emma")
    assert GUEST_HELLO_MARK not in say(s, None)


def test_a_failed_turn_does_not_use_up_the_guest_hello():
    s = santa(replies=(RuntimeError("runner down"), PLAIN))
    say(s, None)
    assert GUEST_HELLO_MARK in say(s, None)


def test_a_failed_turn_does_not_use_up_the_hello():
    s = santa(replies=(RuntimeError("runner down"), PLAIN))
    say(s, "Emma")
    assert s.last_reply.fallback
    assert HELLO_MARK in say(s, "Emma")


def test_a_song_turn_does_not_use_up_the_hello():
    s = santa()
    say(s, "Emma", "can you sing jingle bells")
    assert s.client.calls == []                                  # a song is fixed text, no model call
    assert HELLO_MARK in say(s, "Emma")


def test_a_sad_first_turn_still_greets_and_the_note_says_comfort_first():
    turn = say(santa(), "Emma", "I'm Emma and I'm sad")
    assert HELLO_MARK in turn and "comfort Emma first and ask nothing" in turn
    assert "sounds sad or scared" in turn                        # gentle mode is on too


# -- likes ----------------------------------------------------------------------------------------------------------
def test_second_turn_asks_about_a_remembered_like_never_a_wish():
    s = santa(replies=(PLAIN, ASKS, PLAIN))
    say(s, "Emma")
    turn = say(s, "Emma", "I'm good")
    assert "question about this thing you remember about Emma: likes snow angels" in turn
    assert "drawing pad" not in turn.split("Santa's plan")[-1]   # the wish is never the topic
    assert LIKES_MARK not in say(s, "Emma")                      # Santa asked: done for this call


def test_an_unrelated_question_does_not_end_the_likes_question():
    """Review 2026-11-25: any "?" counted, so "Was it cold outside?" ended the likes question for the call."""
    s = santa(replies=(PLAIN, "Oh, a snowman! Was it cold outside?", "Did you make snow angels today?", PLAIN))
    say(s, "Emma")
    say(s, "Emma", "I made a snowman")
    assert LIKES_MARK in say(s, "Emma")                          # tried again
    assert LIKES_MARK not in say(s, "Emma")                      # asked about the snow angels: done


@pytest.mark.parametrize("spoken, fact, asked", [
    ("What do you like to play?", None, True),
    ("What is your favorite toy?", None, True),
    ("Did you make snow angels today?", "likes snow angels", True),
    ("How is Mittens doing?", "has a cat named Mittens", True),
    ("Was it cold outside?", "likes snow angels", False),
    ("Wow, I like that! Tell me more.", None, False),            # no question
    ("Did you have a good day?", None, False),
])
def test_asked_about_likes(spoken, fact, asked):
    assert guide.asked_about_likes(spoken, fact) is asked


def test_without_a_remembered_like_the_question_is_general():
    s = santa()
    say(s, "Leo")
    turn = say(s, "Leo")
    assert "ONE easy question about something Leo likes" in turn


def test_likes_is_tried_twice_at_most_when_santa_does_not_ask():
    s = santa(replies=(PLAIN,))
    say(s, "Leo")
    assert LIKES_MARK in say(s, "Leo")
    assert LIKES_MARK in say(s, "Leo")
    assert LIKES_MARK not in say(s, "Leo")


def test_likes_waits_while_the_child_is_sad():
    s = santa(replies=(PLAIN,))
    say(s, "Leo")
    assert LIKES_MARK not in say(s, "Leo", "I miss my grandpa")
    for _ in range(persona.GENTLE_TURNS - 1):                    # gentle mode: still no likes question
        assert LIKES_MARK not in say(s, "Leo")


@pytest.mark.parametrize("text", ["can you come to my house", "how much does a pony cost", "can you keep a secret",
                                  "my brother hit me", "are you coming on christmas eve", "can I light the candles",
                                  "my goldfish died"])
def test_likes_waits_on_a_topic_or_loss_turn_and_comes_next(text):
    """The topic's (or the loss's) note answers that turn; a favorite-toy question on top was off topic. The likes
    question is not used up: it comes on the next ordinary turn."""
    s = santa(replies=(PLAIN,))
    say(s, "Leo")
    assert LIKES_MARK not in say(s, "Leo", text)
    if "died" not in text:                                       # a loss also starts gentle mode (test above)
        assert LIKES_MARK in say(s, "Leo", "I like trucks")


def test_the_gift_question_wins_when_both_are_due(monkeypatch):
    monkeypatch.setattr(gifts, "ASK_AT_TURN", 2)                 # both due on Leo's 2nd turn
    s = santa(replies=(PLAIN,))
    say(s, "Leo")
    turn = say(s, "Leo")
    assert "Christmas wish" in turn and LIKES_MARK not in turn


@pytest.mark.parametrize("who", ["Emma", None])
def test_the_gift_question_waits_for_the_hello(monkeypatch, who):
    """Review 2026-11-25: with SANTA_GIFT_ASK_TURN=1 the hello ("ask nothing else") and the gift question were on the
    same turn. The gift question now comes on the next turn, and the held turn is not counted as a try."""
    monkeypatch.setattr(gifts, "ASK_AT_TURN", 1)
    s = santa()
    first = say(s, who)
    assert "first turn talking with you" in first and "Christmas wish" not in first
    assert s.gifts.state(who).tries == 0
    assert "Christmas wish" in say(s, who)


def test_the_remembered_like_rotates_from_call_to_call():
    facts = ["likes dinosaurs", "has a cat named Mittens", "wants a bike", "Last call: talked about snow",
             "has a baby brother named Sam", "loves pancakes"]
    assert guide.like_facts(facts) == ["loves pancakes", "has a cat named Mittens", "likes dinosaurs"]
    assert [guide.pick_fact(facts, n) for n in range(4)] == ["loves pancakes", "has a cat named Mittens",
                                                             "likes dinosaurs", "loves pancakes"]
    assert guide.pick_fact(["wants a puppy for Christmas"], 0) is None
    assert guide.pick_fact([], 3) is None


def test_the_call_count_picks_the_fact():
    kids = {"Emma": {"age": 4, "facts": ["likes dinosaurs", "loves pancakes"]}}
    calllog.record("Emma", NOW - timedelta(days=1))
    s = santa(call_log=True, kids=kids)
    say(s, "Emma")
    assert "remember about Emma: likes dinosaurs" in say(s, "Emma")   # 1 earlier call -> the second-newest


TWO_LIKES = {"Emma": {"age": 4, "facts": ["likes dinosaurs", "loves pancakes"]}}


def _liked(**kw) -> str:
    s = santa(kids=TWO_LIKES, **kw)
    say(s, "Emma")
    return "dinosaurs" if "remember about Emma: likes dinosaurs" in say(s, "Emma") else "pancakes"


def test_without_the_call_log_the_like_changes_from_day_to_day():
    days = [_liked(call_log=False, now=NOW + timedelta(days=d)) for d in range(4)]
    assert set(days) == {"dinosaurs", "pancakes"} and all(a != b for a, b in zip(days, days[1:]))


def test_at_the_call_log_cap_the_like_still_changes_from_day_to_day():
    for i in range(calllog.MAX_PER_CHILD):
        calllog.record("Emma", NOW - timedelta(days=60 - i))
    days = [_liked(call_log=True, now=NOW + timedelta(days=d)) for d in range(3)]
    assert days[0] != days[1] and days[1] != days[2]


def test_a_first_logged_call_uses_the_call_count():
    assert _liked(call_log=True) == "pancakes"                          # 0 earlier calls -> the newest


# -- nice list ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, hit", [
    ("am I on the nice list?", True), ("Am I on the naughty list", True), ("I've been good this year", True),
    ("have I been good?", True), ("was I nice", True), ("I’m good this year", True), ("am I naughty?", True),
    ("I've been naughty", True), ("I'm not naughty", True), ("naughty or nice?", True),
    ("I've been really good for Santa", True), ("have I been good enough", True),
    ("I'm good", False), ("am I good at drawing", False), ("it's been good", False), ("I like lists", False),
    ("my dog is naughty", False), ("my brother was naughty today", False)])
def test_nice_list_cue(text, hit):
    assert cues.talks_nice_list(text) is hit


@pytest.mark.parametrize("text", ["I've been good!", "I've been good", "i have been good", "I've been really good",
                                  "good", "I'm good thanks", "I'm very good", "I've been good at swimming",
                                  "I've been nice to my sister", "I was good at school", "fine", "I've been sick"])
def test_answers_to_how_are_you_are_not_about_the_nice_list(text):
    assert not cues.talks_nice_list(text)


def test_ive_been_good_after_the_hello_gets_no_nice_list_note():
    s = santa()
    say(s, "Emma", "I'm Emma")
    assert "nice list" not in say(s, "Emma", "I've been good!")


def test_any_child_asking_about_the_nice_list_hears_yes_with_no_conditions():
    s = santa()
    turn = say(s, "Emma", "am I on the nice list?")
    assert "Emma is too: say so happily right away, with no conditions" in turn
    assert "the child is too" in say(s, None, "am I on the naughty list?")    # guests too
    assert "nice list" not in say(s, "Leo", "I like trucks")


def test_the_filter_would_cut_naughty_list_so_santa_answers_without_it():
    """Why the note forbids the words: spec.py stops any reply that says "naughty list"."""
    assert spec.safety_reason("Yes, you're on my nice list, not the naughty list!") == "naughty_list"
    assert spec.safety_reason("No! You're on my nice list, Emma!") is None
    assert spec.safety_reason("You're not naughty at all!") is None


# -- notes stay out of history; switches ----------------------------------------------------------------------------
def test_guide_notes_are_never_stored_in_history():
    s = santa()
    say(s, "Emma")
    say(s, "Emma", "am I on the nice list")
    assert not any("Santa's plan" in h["content"] or "nice list." in h["content"] for h in s.history)


def test_santa_guide_0_turns_it_all_off(monkeypatch):
    monkeypatch.setenv("SANTA_GUIDE", "0")
    s = santa()
    assert s.guide is None and not s.nice_on
    for text in ("hi", "hi", "am I on the nice list"):
        turn = say(s, "Emma", text)
        assert HELLO_MARK not in turn and LIKES_MARK not in turn and "no conditions" not in turn


def test_the_stage_i_arc_turns_off_hello_and_likes_but_not_the_nice_list(monkeypatch):
    monkeypatch.setenv("SANTA_ARC", "1")
    s = santa()
    assert s.guide is None and s.nice_on
    assert HELLO_MARK not in say(s, "Emma")
    assert "no conditions" in say(s, "Emma", "am I on the nice list")


def test_with_the_guide_off_the_call_log_note_is_on_every_turn_as_before(monkeypatch):
    monkeypatch.setenv("SANTA_GUIDE", "0")
    calllog.record("Emma", NOW - timedelta(days=1))
    s = santa(call_log=True)
    assert "call log" in say(s, "Emma") and "call log" in say(s, "Emma")


# -- dreams ---------------------------------------------------------------------------------------------------------
def test_the_rules_ask_about_likes_and_not_dreams():
    prompt = santa().system_prompt()
    assert "ask about what the child just said" in prompt and "ask about something the child likes" in prompt
    assert "Never ask about the child's dreams" in prompt and "\"dream gift\" is fine" in prompt
    assert "Never say \"sweet dreams\" unless the note on this turn says it is fine" in prompt


@pytest.mark.parametrize("hour, ok", [(9, False), (16, False), (18, False), (19, True), (20, True), (22, True),
                                      (2, True), (4, True), (5, False)])
def test_sweet_dreams_only_from_7_pm(hour, ok):
    late = datetime(2026, 11, 25, hour, 59 if hour == 18 else 0)
    assert ("\"sweet dreams\" is fine" in persona.time_note(late)) is ok
    assert persona.time_note(late).endswith(".)")


def test_the_sweet_dreams_note_never_says_after_7_pm_after_midnight():
    assert "It is after 7 PM" in persona.time_note(datetime(2026, 11, 25, 22, 0))
    late = persona.time_note(datetime(2026, 11, 26, 2, 15))
    assert "2:15 AM" in late and "7 PM" not in late and "It is the middle of the night, so" in late


def test_sweet_dreams_note_on_an_evening_goodbye():
    s = santa(now=datetime(2026, 11, 25, 19, 45))
    say(s, "Emma")
    assert "\"sweet dreams\" is fine in a goodbye" in say(s, "Emma", "bye bye Santa")


@pytest.mark.parametrize("hour", [19, 22, 2])
@pytest.mark.parametrize("who", ["Emma", None])
def test_a_late_hello_has_no_bedtime_or_dreams_wording(hour, who):
    """Live 2026-11-25, 10:29 PM: the goodbye wording on the hello made Santa open with bed and dreams."""
    s = santa(now=datetime(2026, 11, 25, hour, 29))
    first = say(s, who, "hi Santa, my name is Mikey")
    assert "Your hello should fit the time of day" in first and "Do not ask about bedtime, sleep or dreams" in first
    assert "sweet dreams" not in first and "cozy good night" not in first
    if hour >= 21 or hour < 5:
        assert "never good night" in first


def test_a_first_turn_that_is_a_goodbye_gets_the_goodbye_note():
    s = santa(now=datetime(2026, 11, 25, 19, 45))
    assert "\"sweet dreams\" is fine in a goodbye" in say(s, "Emma", "bye bye Santa")
