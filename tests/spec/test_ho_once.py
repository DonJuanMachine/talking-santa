""""Ho ho ho" once: Santa laughs when he answers the call; after that only when the child sings or tells a joke.

The prompt asks for it (persona.PROMPT_ADDITIONS) and the speech gate enforces it (spec.strip_ho, brain.ho_once).
"""
import _support  # noqa: F401  (temp profiles; must come first)

import time

import numpy as np
import pytest

from santa import cues, persona, spec
from santa.web import canned
from test_spec import make_santa
from test_stage_h import FakeTTS


@pytest.mark.parametrize("text", ["knock knock", "Knock, knock! Who's there?", "I have a joke",
                                  "why did the chicken cross the road", "what do you call a sleepy reindeer",
                                  "jingle bells jingle bells", "can I sing you a song", "la la la", "♪ deck the halls"])
def test_singing_and_jokes_are_recognised(text):
    assert cues.sings_or_jokes(text)


@pytest.mark.parametrize("text", ["hi santa", "I have a dog named Rex", "that's funny", "I want a bike",
                                  "my brother is silly"])
def test_ordinary_turns_are_not(text):
    assert not cues.sings_or_jokes(text)


@pytest.mark.parametrize("raw,out", [
    ("Ho ho ho!", ""),
    ("Ho, ho, ho! Hi Emma!", "Hi Emma!"),
    ("Ho ho, you're so funny!", "You're so funny!"),
    ("That's silly, ho ho!", "That's silly!"),
    ("Wow, ho ho ho, a puppy?", "Wow, a puppy?"),
    ("ho-ho-ho. Merry Christmas!", "Merry Christmas!"),
    ("Holly and Hope said hello.", "Holly and Hope said hello."),      # names starting with Ho are kept
    ("Oh ho! Hi!", "Oh ho! Hi!"),                                       # a single "ho" is not Santa's laugh
])
def test_strip_ho(raw, out):
    assert spec.strip_ho(raw) == out


def test_strip_ho_is_fast_on_long_input():
    t = time.perf_counter()
    spec.strip_ho("ho " * 10000 + "x")
    spec.strip_ho("ho," * 10000)
    assert time.perf_counter() - t < 0.5


def test_santa_does_not_laugh_on_an_ordinary_turn():
    s = make_santa(["Ho ho ho! Hi Emma! Do you like snow?"])
    assert s.reply("Emma", "hi santa") == "Hi Emma! Do you like snow?"
    assert "Ho ho" not in s.history[-1]["content"]                    # the model does not see itself laughing


@pytest.mark.parametrize("child", ["knock knock, who's there? a reindeer!", "twinkle twinkle little star",
                                   "I am singing for you santa, la la la"])
def test_santa_may_laugh_when_the_child_jokes_or_sings(child):
    s = make_santa(["Ho ho ho! That was wonderful, Emma!"])
    assert s.reply("Emma", child) == "Ho ho ho! That was wonderful, Emma!"


def test_a_reply_that_is_only_a_laugh_gives_the_fallback():
    s = make_santa(["Ho ho ho!"])
    assert s.reply("Emma", "hi santa") == spec.FALLBACK


def test_switch_off_restores_the_old_behaviour(monkeypatch):
    monkeypatch.setenv("SANTA_HO_ONCE", "0")
    s = make_santa(["Ho ho ho! Hi Emma!"])
    assert s.reply("Emma", "hi santa") == "Ho ho ho! Hi Emma!"


def test_the_prompt_tells_santa_too():
    p = persona.build_system_prompt({})
    assert 'Do not say "Ho ho" or "Ho ho ho"' in p and "sings to you or tells you a joke" in p
    assert "Ho" not in spec.FALLBACK


class SlowLaughTTS(FakeTTS):
    def __init__(self):
        super().__init__()
        self.speeds = []

    def synth_at(self, line, speed):
        self.speeds.append(speed)
        return self.synth(line)


def test_greeting_starts_with_one_slower_laugh_and_a_pause():
    tts = SlowLaughTTS()
    audio = canned.render_all(tts, None)
    assert tts.speeds == [canned.LAUGH_SPEED]
    laugh, rest = tts.synth(canned.LINES["laugh"]), tts.synth(canned.LINES["greeting"])
    pause = int(tts.sr * canned.LAUGH_PAUSE_S)
    assert len(audio["greeting"]) == len(laugh) + pause + len(rest)
    assert not np.any(audio["greeting"][len(laugh):len(laugh) + pause])            # silence between them
    assert canned.GREETING_SAID == "Ho, ho, ho! Hello, hello! It's Santa! Who am I talking to?"
    assert "Ho" not in canned.TEXT["greeting"]                                      # the laugh is said once


def test_greeting_works_with_a_voice_that_has_no_speed_setting():
    tts = FakeTTS()                                                                 # like Pocket TTS
    audio = canned.render_all(tts, None)
    assert len(audio["greeting"]) > len(tts.synth(canned.LINES["greeting"]))
