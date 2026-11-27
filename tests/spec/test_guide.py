"""Conversation guide (santa/guide.py, 2026-11-25): hello + "how are you" on a registered child's first turn (a welcome
back for a child who called before), one question about what the child likes on the next turn, a yes-with-no-conditions
note when any child talks about the nice list, and "sweet dreams" only from 7 PM. Offline: a fake client, fixed clock."""
import _support  # noqa: F401  (temp profiles; must come first)

import copy
from datetime import datetime, timedelta

import pytest

from _support import FakeClient
from santa import calllog, cues, guide, persona, spec, speech
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


# -- conversation starters ----------------------------------------------------------------------------------------
KIND_MARK = "Have you done something kind or nice for someone today?"
KIND_REPLY_MARK = "answering your question about doing something kind"
GIFT_MARK = "Christmas wish"
QUIET = "I made a snowman"                                       # no question to Santa
KIND_ASKS = "A snowman! Have you done something kind for someone today?"
FAMILY = {"Emma": {"age": 4, "facts": ["likes snow angels"],
                   "family": {"mom": "Mommy", "grandmother": ["Nana", "Granny Fern"], "brother": "Sam"}}}


def ready_for(s, name, starter):
    """Skip to the turn that gets `starter`: the hello and the earlier starters done, one quiet turn already."""
    st = s.guide.kids.setdefault(s.guide._key(name), guide.ChildGuide())
    st.hello_done = True
    st.quiet = guide.QUIET_TURNS - 1
    st.done |= set(guide.STARTERS[:guide.STARTERS.index(starter)])


def test_starters_come_after_two_quiet_turns_in_order_each_once():
    """Don, 2026-11-27: greeting, the child speaks, Santa asks how they are; when the child has not asked anything
    for two turns, a conversation starter: kindness first, then what they like, then the Christmas wish."""
    s = santa(replies=(PLAIN, PLAIN, KIND_ASKS, PLAIN, ASKS, PLAIN, "What would you like for Christmas?", PLAIN))
    turns = [say(s, "Leo", t) for t in ["I'm Leo", "good", QUIET, "yes", "ok", "trucks", "red ones", "a bike"]]
    assert HELLO_MARK.replace("Emma", "Leo") in turns[0]
    assert not any(m in turns[1] for m in (KIND_MARK, LIKES_MARK, GIFT_MARK))      # one quiet turn: not yet
    assert KIND_MARK in turns[2]                                                    # two quiet turns: kindness
    assert KIND_REPLY_MARK in turns[3]                                              # the child's answer
    assert LIKES_MARK in turns[4]                                                   # two quiet turns again
    assert not any(m in turns[5] for m in (KIND_MARK, LIKES_MARK, GIFT_MARK))
    assert GIFT_MARK in turns[6]
    assert not any(m in t for t in [turns[7], say(s, "Leo", "ok"), say(s, "Leo", "ok")]
                   for m in (KIND_MARK, LIKES_MARK, GIFT_MARK, KIND_REPLY_MARK))  # each once per call


def test_a_question_from_the_child_starts_the_count_again():
    s = santa()
    say(s, "Leo", "I'm Leo")
    say(s, "Leo", "good")
    assert KIND_MARK not in say(s, "Leo", "can you fly?")       # the child leads: no starter, count from zero
    assert KIND_MARK not in say(s, "Leo", QUIET)
    assert KIND_MARK in say(s, "Leo", QUIET)


@pytest.mark.parametrize("text, asks", [("can you fly", True), ("do you like cookies", True), ("what's your name?",
                         True), ("um, is it snowing there", True), ("Rudolph is red?", True), ("I like trucks", False),
                         ("good", False), ("I made a snowman", False), ("I wonder if you are real", False)])
def test_asks_santa(text, asks):
    assert cues.asks_santa(text) is asks


def test_the_kindness_reply_suggests_a_hug_for_someone_from_the_family_list():
    s = santa(replies=(KIND_ASKS, PLAIN), kids=FAMILY)
    ready_for(s, "Emma", guide.KINDNESS)
    assert KIND_MARK in say(s, "Emma", QUIET)
    reply = say(s, "Emma", "no")
    assert KIND_REPLY_MARK in reply and "That's okay! You could give " in reply
    assert any(f"give {n} a big hug" in reply for n in ("Mommy", "Nana", "Sam"))
    assert "Never mention the nice or naughty list" in reply and "comfort Emma first" in reply


def test_the_family_pick_rotates_and_falls_back_to_someone_who_needs_it():
    assert guide.family_names(FAMILY["Emma"]) == ["Mommy", "Nana", "Sam"]        # first name per relation
    assert [guide.pick_family(FAMILY["Emma"], n) for n in range(4)] == ["Mommy", "Nana", "Sam", "Mommy"]
    assert guide.pick_family({"age": 3}, 1) is None and guide.pick_family(None, 0) is None
    assert "give someone who needs it a big hug" in persona.kind_reply_note("Leo", None)


@pytest.mark.parametrize("who", ["Leo", None])
def test_without_a_family_list_or_as_a_guest_the_hug_is_for_someone_who_needs_it(who):
    s = santa(replies=(KIND_ASKS, PLAIN))
    ready_for(s, who, guide.KINDNESS)
    say(s, who, QUIET)
    assert "give someone who needs it a big hug" in say(s, who, "no")


def test_the_kindness_reply_waits_out_a_sad_answer():
    s = santa(replies=(KIND_ASKS, PLAIN))
    ready_for(s, "Leo", guide.KINDNESS)
    say(s, "Leo", QUIET)
    assert KIND_REPLY_MARK not in say(s, "Leo", "no, I'm sad, my fish died")
    assert KIND_REPLY_MARK not in say(s, "Leo", "ok")           # the moment passed


def test_a_starter_santa_does_not_ask_is_tried_twice_then_the_next_one_comes():
    s = santa(replies=(PLAIN,))
    ready_for(s, "Leo", guide.KINDNESS)
    assert KIND_MARK in say(s, "Leo", QUIET)
    assert KIND_MARK in say(s, "Leo", QUIET)
    assert LIKES_MARK in say(s, "Leo", QUIET)


def test_the_hello_turn_never_carries_a_starter():
    for who in ("Emma", None):
        turn = say(santa(), who, "I'm Emma")
        assert not any(m in turn for m in (KIND_MARK, LIKES_MARK, GIFT_MARK))


def test_the_wish_question_is_skipped_once_gifts_came_up_and_off_with_its_switch(monkeypatch):
    s = santa()
    ready_for(s, "Leo", guide.GIFT)
    say(s, "Leo", "I want a bike for Christmas")                 # gifts came up (and that turn is not quiet anyway)
    assert all(GIFT_MARK not in say(s, "Leo", QUIET) for _ in range(3))
    monkeypatch.setenv("SANTA_GIFT_ASK", "0")
    s = santa()
    ready_for(s, "Leo", guide.GIFT)
    assert GIFT_MARK not in say(s, "Leo", QUIET)


@pytest.mark.parametrize("first", [None, "Zed"])
def test_a_guest_gets_the_hello_once_then_the_starters(first):
    """2026-11-25 (Don, calling as a guest): Santa went straight to "What toys do you like?" with no hello. Guests
    share one slot; since 2026-11-27 they get the conversation starters too."""
    s = santa()
    turn = say(s, first, "Don")
    assert GUEST_HELLO_MARK in turn and "ask nothing else" in turn and "comfort the child first" in turn
    assert "by name" not in turn and "again" not in turn and "call log" not in turn
    later = [say(s, speaker, QUIET) for speaker in (None, "Zed")]   # guests share one slot
    assert GUEST_HELLO_MARK not in later[0] + later[1]
    assert KIND_MARK in later[1] and "Then ask:" in later[1]


# -- slow wrap-up ---------------------------------------------------------------------------------------------------
WRAP_MARK = "If you don't have any questions for Santa, you can go and enjoy your day"
WRAP_REPLY_MARK = "answering whether they want to talk more"
WRAPS = "Lovely! " + persona.WRAP_LINE
TWO_FACTS = {"Emma": {"age": 4, "facts": ["likes snow angels", "has a cat named Mittens"]}}


def ready_for_wrap(s, name, done=guide.STARTERS):
    """Skip to the turn that gets the wrap-up: the hello and `done` starters done, WRAP_AFTER - 1 answers already."""
    st = s.guide.kids.setdefault(s.guide._key(name), guide.ChildGuide())
    st.hello_done = True
    st.answers = guide.WRAP_AFTER - 1
    st.done |= set(done)


def test_a_quiet_call_gets_the_wrap_up_on_the_seventh_answer_after_the_starters():
    """Don, 2026-11-27: after 7 answers with no question to Santa, a slow wrap-up."""
    s = santa(replies=(PLAIN, PLAIN, KIND_ASKS, PLAIN, ASKS, PLAIN, "What would you like for Christmas?", WRAPS, PLAIN))
    turns = [say(s, "Leo", t) for t in ["I'm Leo"] + ["ok"] * 8]
    assert [i for i, t in enumerate(turns) if WRAP_MARK in t] == [guide.WRAP_AFTER]   # the 7th answer after the hello
    assert "Ask nothing else" in turns[guide.WRAP_AFTER] and "comfort Leo first" in turns[guide.WRAP_AFTER]
    assert WRAP_REPLY_MARK in turns[guide.WRAP_AFTER + 1]


def test_a_question_from_the_child_starts_the_wrap_up_count_again():
    s = santa()
    ready_for_wrap(s, "Leo")
    assert WRAP_MARK not in say(s, "Leo", "do you have a dog?")
    for _ in range(guide.WRAP_AFTER - 1):
        assert WRAP_MARK not in say(s, "Leo", "ok")
    assert WRAP_MARK in say(s, "Leo", "ok")


def test_no_wrap_up_on_a_sad_or_topic_turn():
    for text in ["I'm sad", "can you come to my house", "my fish died"]:
        s = santa()
        ready_for_wrap(s, "Leo")
        assert WRAP_MARK not in say(s, "Leo", text)


def test_after_yes_the_wish_question_comes_if_it_was_never_asked():
    s = santa(replies=(WRAPS, PLAIN))
    ready_for_wrap(s, "Leo", done=(guide.KINDNESS, guide.LIKES))
    say(s, "Leo", "ok")
    reply = say(s, "Leo", "yes")
    assert WRAP_REPLY_MARK in reply and "Is there something special you want for Christmas?" in reply
    assert "warm goodbye" in reply and "Never promise a gift" in reply


def test_after_yes_a_remembered_like_not_asked_yet_then_a_general_question():
    s = santa(replies=(ASKS, PLAIN, WRAPS, "Yay! How is Mittens doing?") + (PLAIN,) * 6 + (WRAPS, PLAIN), kids=TWO_FACTS)
    ready_for(s, "Emma", guide.LIKES)
    assert "remember about Emma: likes snow angels" in say(s, "Emma", QUIET)       # the likes starter asks one
    st = s.guide.kids["emma"]
    st.done |= {guide.GIFT}
    st.answers = guide.WRAP_AFTER - 2
    say(s, "Emma", "ok")
    assert WRAP_MARK in say(s, "Emma", "ok")
    first = say(s, "Emma", "yes")
    assert "remember about Emma: has a cat named Mittens" in first                 # not the snow angels again
    for _ in range(guide.WRAP_AFTER - 1):
        say(s, "Emma", "ok")
    assert WRAP_MARK in say(s, "Emma", "ok")                                       # again after 7 more answers
    second = say(s, "Emma", "yes")
    assert "about something Emma likes to play" in second                          # no remembered like left


AFTER_BYE_MARK = "You already said goodbye to"


def test_after_the_goodbye_santa_starts_nothing_new_until_the_child_asks_something():
    """Live 2026-11-27: after "It was so nice talking with you! Merry Christmas!" the child's "ok" got a new question."""
    s = santa(replies=(WRAPS, "It was so nice talking with you! Merry Christmas!", PLAIN))
    ready_for_wrap(s, "Leo")
    say(s, "Leo", "ok")
    say(s, "Leo", "no thanks")
    for _ in range(guide.WRAP_AFTER - 2):
        turn = say(s, "Leo", "ok")
        assert AFTER_BYE_MARK in turn and "ask nothing" in turn
        assert not any(m in turn for m in (KIND_MARK, LIKES_MARK, GIFT_MARK, WRAP_MARK))
    assert WRAP_MARK in say(s, "Leo", "ok")                      # still talking 7 answers later: offer again
    s = santa(replies=(WRAPS, "It was so nice talking with you! Merry Christmas!", PLAIN))
    ready_for_wrap(s, "Leo")
    say(s, "Leo", "ok")
    say(s, "Leo", "bye Santa")
    assert AFTER_BYE_MARK not in say(s, "Leo", "wait, do reindeer eat carrots?")   # a question: talking again
    assert AFTER_BYE_MARK not in say(s, "Leo", "ok")


def test_after_yes_there_is_no_goodbye_state():
    s = santa(replies=(WRAPS, "Yay! What do you like to play?", PLAIN))
    ready_for_wrap(s, "Leo")
    say(s, "Leo", "ok")
    say(s, "Leo", "yes")
    assert AFTER_BYE_MARK not in say(s, "Leo", "trucks")


def test_a_wrap_up_santa_does_not_say_is_tried_once_more():
    s = santa(replies=(PLAIN,))
    ready_for_wrap(s, "Leo")
    assert WRAP_MARK in say(s, "Leo", "ok")
    assert WRAP_MARK in say(s, "Leo", "ok")
    assert WRAP_MARK not in say(s, "Leo", "ok")


@pytest.mark.parametrize("spoken, asked", [
    (persona.WRAP_LINE, True), ("Do you want to chat a little longer?", True), ("You can go and enjoy your day!", False),
    ("Would you like to hear about my reindeer?", False)])
def test_asked_wrap(spoken, asked):
    assert guide.asked_wrap(spoken) is asked


def test_the_wrap_up_line_passes_every_rule_and_keeps_its_question_after_a_short_answer():
    assert spec.safety_reason(persona.WRAP_LINE) is None
    for answer in ("Snowmen are so fun, Leo!", "Ho ho ho! Snowmen are so fun, Leo!"):
        heard = speech.filter_reply(f"{answer} {persona.WRAP_LINE}").text
        assert heard.endswith("Would you like to talk some more?"), heard


def test_a_weather_like_gets_the_weather_note_and_other_facts_do_not():
    """Live 2026-11-27: with "likes snow angels" remembered, Santa sometimes asked "Did you play in the snow today?"."""
    turn = say(santa(), "Emma", "I'm Emma")                         # Emma: "likes snow angels"
    assert "never assume it is snowy, cold, rainy or sunny where Emma is now" in turn
    assert "never assume it is snowy" not in say(santa(kids={"Leo": {"age": 3, "facts": ["has a cat named Mittens"]}}),
                                                "Leo", "I'm Leo")
    assert [cues.weather_like(f) for f in ["likes snow angels", "loves the beach", "likes sledding", "has a cat",
                                           "likes trucks", "likes ice cream"]] == [True, True, True, False, False, True]


def test_the_weather_note_has_an_off_switch(monkeypatch):
    monkeypatch.setenv("SANTA_WEATHER_NOTE", "0")
    turn = say(santa(), "Emma", "I'm Emma")
    assert "never assume it is snowy" not in turn and "likes snow angels" in turn       # the facts note stays


def test_santa_asking_about_the_remembered_like_on_his_own_uses_up_the_likes_starter():
    """Live 2026-11-27: "Do you like to make snow angels?" on turn 2 by himself, then again from the likes starter."""
    s = santa(replies=(PLAIN, "Do you like to make snow angels?", KIND_ASKS, PLAIN, PLAIN, PLAIN))
    say(s, "Emma", "I'm Emma")
    say(s, "Emma", "good")                                          # Santa asks about the snow angels on his own
    turns = [say(s, "Emma", t) for t in [QUIET, "no", "ok", "ok"]]
    assert KIND_MARK in turns[0]
    assert not any("thing you remember about Emma" in t for t in turns)
    assert guide.LIKES in s.guide.state("Emma").done and "likes snow angels" in s.guide.state("Emma").facts_asked


def test_santa_is_told_never_to_wrap_up_on_his_own():
    assert "Never start saying goodbye or wrapping up the talk on your own" in santa().system_prompt()


# -- likes ----------------------------------------------------------------------------------------------------------
def test_likes_asks_about_a_remembered_like_never_a_wish():
    s = santa(replies=(ASKS, PLAIN))
    ready_for(s, "Emma", guide.LIKES)
    turn = say(s, "Emma", QUIET)
    assert "question about this thing you remember about Emma: likes snow angels" in turn
    assert "drawing pad" not in turn.split("Santa's plan")[-1]   # the wish is never the topic
    assert LIKES_MARK not in say(s, "Emma", QUIET)               # Santa asked: done for this call


def test_an_unrelated_question_does_not_end_the_likes_question():
    """Review 2026-11-25: any "?" counted, so "Was it cold outside?" ended the likes question for the call."""
    s = santa(replies=("Oh, a snowman! Was it cold outside?", "Did you make snow angels today?", PLAIN))
    ready_for(s, "Emma", guide.LIKES)
    say(s, "Emma", QUIET)
    assert "thing you remember about Emma" in say(s, "Emma", QUIET)       # tried again
    assert "thing you remember about Emma" not in say(s, "Emma", QUIET)   # asked about the snow angels: done


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


@pytest.mark.parametrize("spoken, asked", [
    ("Have you done something kind for someone today?", True), ("Did you help anyone today?", True),
    ("Were you nice to your sister?", True), ("What did you do today?", False), ("You are so kind!", False)])
def test_asked_kindness(spoken, asked):
    assert guide.asked_kindness(spoken) is asked


def test_without_a_remembered_like_the_question_is_general():
    s = santa()
    ready_for(s, "Leo", guide.LIKES)
    assert "ONE easy question about something Leo likes" in say(s, "Leo", QUIET)


def test_likes_waits_while_the_child_is_sad():
    s = santa(replies=(PLAIN,))
    ready_for(s, "Leo", guide.LIKES)
    assert LIKES_MARK not in say(s, "Leo", "I miss my grandpa")
    for _ in range(persona.GENTLE_TURNS - 1):                    # gentle mode: still no likes question
        assert LIKES_MARK not in say(s, "Leo", QUIET)


@pytest.mark.parametrize("text", ["can you come to my house", "how much does a pony cost", "can you keep a secret",
                                  "my brother hit me", "are you coming on christmas eve", "can I light the candles",
                                  "my goldfish died"])
def test_likes_waits_on_a_topic_or_loss_turn_and_comes_later(text):
    """The topic's (or the loss's) note answers that turn; a favorite-toy question on top was off topic. The likes
    question is not used up: the child led that turn, so it comes after two more quiet turns."""
    s = santa(replies=(PLAIN,))
    ready_for(s, "Leo", guide.LIKES)
    assert LIKES_MARK not in say(s, "Leo", text)
    if "died" not in text:                                       # a loss also starts gentle mode (test above)
        assert LIKES_MARK not in say(s, "Leo", QUIET)
        assert LIKES_MARK in say(s, "Leo", QUIET)


def test_the_remembered_like_rotates_from_call_to_call():
    facts = ["likes dinosaurs", "has a cat named Mittens", "wants a bike", "Last call: talked about snow",
             "has a baby brother named Sam", "loves pancakes"]
    assert guide.like_facts(facts) == ["loves pancakes", "has a cat named Mittens", "likes dinosaurs"]
    assert [guide.pick_fact(facts, n) for n in range(4)] == ["loves pancakes", "has a cat named Mittens",
                                                             "likes dinosaurs", "loves pancakes"]
    assert guide.pick_fact(["wants a puppy for Christmas"], 0) is None
    assert guide.pick_fact([], 3) is None


TWO_LIKES = {"Emma": {"age": 4, "facts": ["likes dinosaurs", "loves pancakes"]}}


def _liked(**kw) -> str:
    s = santa(kids=kw.pop("kids", TWO_LIKES), **kw)
    say(s, "Emma")                                               # the hello (and the call log, if on)
    ready_for(s, "Emma", guide.LIKES)
    return "dinosaurs" if "remember about Emma: likes dinosaurs" in say(s, "Emma", QUIET) else "pancakes"


def test_the_call_count_picks_the_fact():
    calllog.record("Emma", NOW - timedelta(days=1))
    assert _liked(call_log=True) == "dinosaurs"                  # 1 earlier call -> the second-newest


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
