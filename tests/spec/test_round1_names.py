"""Fix round 1, P4-2 (names part only; review pass 4): the gift-promise name rule was given the active child's name and
nicknames only, so "Wren will get a pony too!" on Juniper's gift turn was spoken. The brain now passes every registered
child's name (the active child's first, with the active child's nicknames). Fixture names only.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import pytest
from _support import FakeClient

from santa import brain, memory, spec

FB = spec.FALLBACK
PROFILES = {"Juniper": {"age": 4, "facts": [], "nicknames": ["Junie"]}, "Wren": {"age": 3, "facts": []},
            "Leo": {"age": 3, "facts": []}}


@pytest.fixture(autouse=True)
def _no_real_profiles(tmp_path, monkeypatch):
    real_save = memory.save
    monkeypatch.setattr(memory, "save", lambda profiles, path=tmp_path / "p.json": real_save(profiles, path))


def say(child, reply, speaker="Juniper", chunk=3):
    s = brain.Santa(model="fake", client=FakeClient([reply], chunk=chunk),
                    profiles={k: dict(v) for k, v in PROFILES.items()})
    s.last_ok_time = brain._now()
    return s.reply(speaker, child), s


@pytest.mark.parametrize("chunk", [1, 3, 50])
@pytest.mark.parametrize("reply", ["Wren will get a pony too!", "And I'll bring Wren a truck!"])
def test_p4_2_a_siblings_name_in_a_promise_is_stopped_on_a_gift_turn(reply, chunk):
    heard, s = say("Can I have a pony?", reply, chunk=chunk)
    assert heard == FB
    assert s.last_reply.reason == "blocklist:promise"


@pytest.mark.parametrize("reply", ["I'll bring Leo a bike!", "Leo will get a bike!"])
def test_p4_2_a_siblings_name_in_a_promise_is_stopped_on_any_turn(reply):
    assert say("hi santa", reply)[0] == FB


def test_p4_2_names_are_every_registered_child_active_first():
    s = brain.Santa(model="fake", client=FakeClient(), profiles={k: dict(v) for k, v in PROFILES.items()})
    assert s._names("Juniper") == ["Juniper", "Junie", "Wren", "Leo"]
    assert s._names("Wren") == ["Wren", "Juniper", "Leo"]
    assert s._names(None) == ["Juniper", "Wren", "Leo"]


@pytest.mark.parametrize("reply", ["Wren, the elves will make toys all night long!", "Say hi to Wren for me!",
                                   "Wren will get so big this year!", "Do you and Wren like snow?"])
def test_p4_2_a_sibling_mentioned_without_a_promise_is_still_spoken(reply):
    assert say("Can I have a pony?", reply)[0] == reply
