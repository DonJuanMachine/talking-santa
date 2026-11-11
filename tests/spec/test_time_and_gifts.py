"""Time-of-day note and the gift question (2026-11-10). Offline: a fake model client, a fixed clock."""
import _support  # noqa: F401  (temp profiles; must come first)

import copy
from datetime import datetime
from types import SimpleNamespace

import pytest

from _support import _chunk
from santa import cues, gifts, persona
from santa.brain import Santa

KIDS = {"Emma": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": []}}
PLAIN = "Ho ho! That sounds lovely."
NOTE_MARK = "Christmas wish"           # text only the gift note contains
MORNING = datetime(2026, 11, 10, 9, 5)


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.delenv("SANTA_ARC", raising=False)
    monkeypatch.delenv("SANTA_GIFT_ASK", raising=False)
    monkeypatch.delenv("SANTA_TIME_NOTE", raising=False)


class Fake:
    """Streams `replies` in turn (the last one repeats) and records every streamed request."""

    def __init__(self, replies):
        self.replies, self.k, self.requests = list(replies), 0, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **_):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="h"))]))))

    def _create(self, **kw):
        if not kw.get("stream"):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"facts": []}'))])
        self.requests.append(copy.deepcopy(kw["messages"]))
        r = self.replies[min(self.k, len(self.replies) - 1)]
        self.k += 1
        return iter([_chunk(r[i:i + 3]) for i in range(0, len(r), 3)])


def santa(replies=(PLAIN,), now=MORNING):
    s = Santa(client=Fake(replies), profiles=copy.deepcopy(KIDS))
    s.last_ok_time = 1e18
    s.clock = lambda: now
    return s


def last_turn(s) -> str:
    return s.client.requests[-1][-1]["content"]


def say(s, speaker, text):
    for _ in s.reply_stream(speaker, text):
        pass
    return last_turn(s)


# ------------------------------------------------------------------------------------------------- time of day
@pytest.mark.parametrize("hour,part", [(5, "morning"), (9, "morning"), (11, "morning"), (12, "afternoon"),
                                       (16, "afternoon"), (17, "evening"), (20, "evening"), (21, "night"),
                                       (0, "night"), (4, "night")])
def test_part_of_day(hour, part):
    assert persona.part_of_day(hour) == part


def test_time_note_morning_says_no_good_night():
    n = persona.time_note(MORNING)
    assert "morning right now: 9:05 AM on Tuesday" in n and "never good night" in n


@pytest.mark.parametrize("h,m,clock", [(0, 0, "12:00 AM"), (12, 30, "12:30 PM"), (21, 5, "9:05 PM")])
def test_clock_format(h, m, clock):
    assert clock in persona.time_note(datetime(2026, 11, 10, h, m))


def test_time_note_on_first_turn_and_goodbyes_only():
    s = santa()
    assert "9:05 AM" in say(s, "Emma", "hi santa")                 # first turn of the call
    assert "9:05 AM" not in say(s, "Emma", "i like snow")          # mid-chat: none (Santa re-greeted live)
    assert "9:05 AM" not in say(s, None, "hello")                  # a guest mid-chat: none
    assert "9:05 AM" in say(s, "Emma", "bye santa i have to go")   # goodbye
    for req in s.client.requests:
        assert "9:05 AM" not in req[0]["content"]                  # system prompt unchanged
    assert all("9:05" not in h["content"] for h in s.history)


@pytest.mark.parametrize("text,yes", [("bye santa", True), ("goodbye!", True), ("I have to go now", True),
                                      ("good night santa", True), ("gotta go", True), ("see you later", True),
                                      ("i like snow", False), ("my dog is a boy", False), ("I want to go sledding", False)])
def test_sounds_like_goodbye(text, yes):
    assert cues.sounds_like_goodbye(text) is yes


def test_time_note_off(monkeypatch):
    monkeypatch.setenv("SANTA_TIME_NOTE", "0")
    s = santa()
    assert "right now" not in say(s, "Emma", "hi santa")


def test_clock_is_read_each_turn():
    s = santa()
    say(s, "Emma", "hi")
    s.clock = lambda: datetime(2026, 11, 10, 19, 40)
    assert "evening right now: 7:40 PM" in say(s, "Emma", "bye bye")


# ----------------------------------------------------------------------------------------------- gift question
@pytest.mark.parametrize("text", ["I want a bike", "can you bring me a doll", "my wish is a puppy",
                                  "I'd like a train", "what presents do the elves make", "I made a Christmas list",
                                  "I hope for christmas I get a kite", "I wanna dinosaur"])
def test_talks_gifts_yes(text):
    assert gifts.talks_gifts(text)


@pytest.mark.parametrize("text", ["I like snow", "my cat is named Mittens", "are you real", "Merry Christmas!",
                                  "Are you excited for Christmas morning?"])
def test_talks_gifts_no(text):
    assert not gifts.talks_gifts(text)


@pytest.mark.parametrize("reply,yes", [
    ("Does your cat like to play with toys?", False),          # live check: this must NOT count as gift talk
    ("Are you excited for Christmas morning?", False),
    ("What would you like for Christmas, Emma?", True),
    ("What is something special you are hoping for this Christmas?", True),
    ("I'll tell my elves about your wish!", True),
    ("What should Santa bring you?", True),
])
def test_santa_talks_gifts(reply, yes):
    assert gifts.santa_talks_gifts(reply) is yes


@pytest.mark.parametrize("text", ["my dog died", "i miss him", "I'm sad", "i got hurt", "I'm scared of the dark"])
def test_sounds_sad(text):
    assert cues.sounds_sad(text)


def test_santa_mentioning_toys_does_not_skip_the_question():
    s = santa(replies=["Does your cat like to play with toys?"])
    for i in range(4):
        say(s, "Emma", f"snow {i}")
    assert NOTE_MARK in say(s, "Emma", "fluffy")


def test_any_christmas_question_on_a_note_turn_counts_as_asked():
    s = santa(replies=[PLAIN] * 4 + ["What fun thing do you hope to do this Christmas?", PLAIN])
    for i in range(4):
        say(s, "Emma", f"snow {i}")
    assert NOTE_MARK in say(s, "Emma", "fluffy")
    assert NOTE_MARK not in say(s, "Emma", "dancing")


def test_no_note_on_a_sad_turn_or_the_next_two():
    s = santa()
    for i in range(4):
        say(s, "Emma", f"snow {i}")
    assert NOTE_MARK not in say(s, "Emma", "my dog died")                # turn 5: sad
    assert NOTE_MARK not in say(s, "Emma", "he was brown")               # cooldown 1
    assert NOTE_MARK not in say(s, "Emma", "we had a park")              # cooldown 2
    assert NOTE_MARK in say(s, "Emma", "i like cocoa")                   # back


def test_another_sad_turn_restarts_the_pause():
    s = santa()
    for i in range(4):
        say(s, "Emma", f"snow {i}")
    say(s, "Emma", "my dog died")
    say(s, "Emma", "he was brown")
    assert NOTE_MARK not in say(s, "Emma", "i miss him")
    assert NOTE_MARK not in say(s, "Emma", "ok")
    assert NOTE_MARK not in say(s, "Emma", "ok")
    assert NOTE_MARK in say(s, "Emma", "i like cocoa")


def test_note_appears_on_turn_5_only_when_gifts_never_came_up():
    s = santa()
    for i in range(4):
        assert NOTE_MARK not in say(s, "Emma", f"I like snow {i}")
    assert NOTE_MARK in say(s, "Emma", "my cat is fluffy")                 # turn 5


def test_no_note_when_child_already_talked_about_gifts():
    s = santa()
    say(s, "Emma", "I want a bike")
    for i in range(6):
        assert NOTE_MARK not in say(s, "Emma", f"snow {i}")


def test_no_note_when_santa_already_asked():
    s = santa(replies=["What would you like for Christmas, Emma?", PLAIN])
    say(s, "Emma", "hi")
    for i in range(6):
        assert NOTE_MARK not in say(s, "Emma", f"snow {i}")


def test_note_stops_once_the_ask_lands():
    s = santa(replies=[PLAIN] * 4 + ["Is there something special you want for Christmas?", PLAIN])
    for i in range(4):
        say(s, "Emma", f"snow {i}")
    assert NOTE_MARK in say(s, "Emma", "fluffy")                           # turn 5: Santa asks
    assert NOTE_MARK not in say(s, "Emma", "a red ball")                   # turn 6: done


def test_retries_at_most_three_turns_then_gives_up():
    s = santa()
    seen = [NOTE_MARK in say(s, "Emma", f"snow {i}") for i in range(10)]
    assert seen == [False] * 4 + [True] * 3 + [False] * 3


def test_each_child_counted_separately():
    s = santa()
    for i in range(4):
        say(s, "Emma", f"snow {i}")
        assert NOTE_MARK not in say(s, "Leo", f"truck {i}")
    assert NOTE_MARK in say(s, "Emma", "fluffy")
    assert "Emma" in last_turn(s).split("Christmas wish")[0]
    assert NOTE_MARK in say(s, "Leo", "vroom")


def test_guest_gets_the_note_with_a_neutral_name():
    s = santa()
    for i in range(4):
        say(s, None, f"snow {i}")
    t = say(s, None, "hi")
    assert NOTE_MARK in t and "the child's Christmas wish" in t


def test_note_keeps_the_safety_suffix_and_never_promise():
    n = persona.gift_note("Emma")
    assert "Never promise a gift" in n and "comfort Emma first and ask nothing" in n
    assert "What would you like for Christmas?" in n


def test_fallback_turn_does_not_count():
    s = santa(replies=[""])                                                # empty stream -> FALLBACK
    for i in range(6):
        say(s, "Emma", f"snow {i}")
    assert s.gifts.state("Emma").turns == 0


def test_off_switch_and_off_with_arc(monkeypatch):
    monkeypatch.setenv("SANTA_GIFT_ASK", "0")
    assert santa().gifts is None
    monkeypatch.setenv("SANTA_GIFT_ASK", "1")
    monkeypatch.setenv("SANTA_ARC", "1")
    assert santa().gifts is None


def test_gift_note_never_stored_in_history():
    s = santa()
    for i in range(6):
        say(s, "Emma", f"snow {i}")
    assert all(NOTE_MARK not in h["content"] for h in s.history)


# ------------------------------------------------------------------------------------------------- gentle mode
GENTLE_MARK = "no \"Ho ho ho\""


def test_gentle_on_the_sad_turn_and_the_next_three():
    s = santa()
    assert GENTLE_MARK not in say(s, "Emma", "i like snow")
    t = say(s, "Emma", "my dog died")
    assert GENTLE_MARK in t and "sounds sad" in t and "ask nothing" in t
    for line in ["he was brown", "we had a park", "i like cocoa"]:
        t = say(s, "Emma", line)
        assert GENTLE_MARK in t and "was sad a moment ago" in t
    assert GENTLE_MARK not in say(s, "Emma", "i like dancing")


def test_another_sad_turn_restarts_gentle():
    s = santa()
    say(s, "Emma", "my dog died")
    say(s, "Emma", "ok")
    say(s, "Emma", "i miss him")
    for _ in range(3):
        assert GENTLE_MARK in say(s, "Emma", "ok")
    assert GENTLE_MARK not in say(s, "Emma", "ok")


def test_gentle_is_per_child_and_guest_neutral():
    s = santa()
    say(s, "Emma", "my dog died")
    assert GENTLE_MARK not in say(s, "Leo", "i like trucks")
    assert GENTLE_MARK in say(s, "Emma", "ok")
    assert "the child sounds sad" in say(s, None, "i'm scared")


def test_gentle_off_switch_and_never_in_history(monkeypatch):
    s = santa()
    say(s, "Emma", "my dog died")
    assert all(GENTLE_MARK not in h["content"] for h in s.history)
    monkeypatch.setenv("SANTA_GENTLE", "0")
    assert GENTLE_MARK not in say(santa(), "Emma", "my dog died")
