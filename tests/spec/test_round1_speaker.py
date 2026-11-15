"""Fix round 1, P4-4 (review pass 4): any voice near the microphone is the child's turn, and a registered name heard
once switched the speaker. A parent's "Wren, wait your turn." made Wren (child B) the speaker while child A was still
talking, and A's next words were answered and stored as B's.

Owner decision: the active speaker changes only when the child introduces themself ("I'm X", "I am X", "my name is
X", "this is X"; also "it's X", pinned by an older test) or when the adult presses the child's button. A name that merely appears in a sentence does not
switch. remember() is not called for a turn whose transcript names a registered child other than the active one; the
turn is still answered. No loudness-based dropping of turns (quiet children must be heard). Fixture names only.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import asyncio

import pytest
from _support import FakeClient
from test_stage_h import FakeSTT, make, say, until, wait_mic_open, wait_state

from santa.web.session import State, heard_name

NAMES = ["Juniper", "Wren"]
ALIASES = {"junie": "Juniper"}
PROFILES = {"Juniper": {"age": 4, "facts": [], "nicknames": ["Junie"]}, "Wren": {"age": 3, "facts": []}}


# ------------------------------------------------------------------ heard_name: introductions only
@pytest.mark.parametrize("text,who", [
    ("I'm Wren", "Wren"), ("i'm wren", "Wren"), ("I am Wren.", "Wren"), ("my name is Wren", "Wren"),
    ("This is WREN!", "Wren"), ("hi santa this is wren", "Wren"), ("Hi Santa, I'm Wren and I like dinosaurs", "Wren"),
    ("I'm Junie", "Juniper"), ("my name is Juniper", "Juniper"), ("hi santa it's wren", "Wren"),
])
def test_p4_4_an_introduction_names_the_speaker(text, who):
    assert heard_name(text, NAMES, ALIASES) == who


@pytest.mark.parametrize("text", [
    "Wren, wait your turn.", "tell Wren hi", "Wren", "Wren is my sister", "I want to play with Wren",
    "Junie, sit down please", "is this Wren's turn?", "I'm Wren's sister", "I'm Juniper and that's Wren",
    "I'm Wren, I'm Wren", "I'm wrenching it", "it's Wren's turn", "is it Wren?",
])
def test_p4_4_a_name_in_a_sentence_is_not_an_introduction(text):
    assert heard_name(text, NAMES, ALIASES) is None


# ------------------------------------------------------------------ the call: who is speaking, what is remembered
def _session(transcripts, replies=("That sounds lovely!",)):
    sess, b, brain, stt, tts = make(client=FakeClient(replies=list(replies)), stt=FakeSTT(transcripts),
                                    profiles=PROFILES)
    calls = []
    real = brain.remember
    brain.remember = lambda speaker, text: (calls.append((speaker, text)), real(speaker, text))[1]
    return sess, b, brain, calls


async def _turn(sess, n):
    """One child turn; returns when Santa has answered it and the mic is open again (remember() has been queued)."""
    await say(sess, 1.0)
    await until(lambda: len(sess.metrics) == n)
    await wait_mic_open(sess)
    await asyncio.sleep(0.05)


def _last_user_turn(brain):
    return brain.santa.history[-2]["content"]


def test_p4_4_a_parent_saying_another_childs_name_does_not_switch_or_store():
    async def go():
        sess, b, brain, calls = _session(["Wren, wait your turn."])
        await sess.call()
        await wait_mic_open(sess)
        await sess.set_child("Juniper")
        await _turn(sess, 1)
        assert sess.active == "Juniper"
        assert _last_user_turn(brain).startswith("Juniper: ")      # answered, as Juniper's turn
        assert calls == []                                           # not remembered
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_p4_4_tell_wren_hi_is_answered_but_not_remembered():
    async def go():
        sess, b, brain, calls = _session(["tell Wren hi"])
        await sess.call()
        await wait_mic_open(sess)
        await sess.set_child("Juniper")
        await _turn(sess, 1)
        assert sess.active == "Juniper"
        assert sess.counters["turns"] == 1                           # Santa answered it
        assert calls == []
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_p4_4_im_wren_switches_and_is_remembered_for_wren():
    async def go():
        sess, b, brain, calls = _session(["I'm Wren"])
        await sess.call()
        await wait_mic_open(sess)
        await sess.set_child("Juniper")
        await _turn(sess, 1)
        assert sess.active == "Wren"
        assert _last_user_turn(brain).startswith("Wren: ")
        await until(lambda: calls == [("Wren", "I'm Wren")])
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_p4_4_the_button_switches_and_the_next_turn_is_remembered_for_that_child():
    async def go():
        sess, b, brain, calls = _session(["I like snow"])
        await sess.call()
        await wait_mic_open(sess)
        await sess.set_child("Juniper")
        await sess.set_child("Wren")
        assert sess.active == "Wren"
        await _turn(sess, 1)
        assert sess.active == "Wren"
        await until(lambda: calls == [("Wren", "I like snow")])
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_p4_4_naming_the_active_child_is_still_remembered():
    async def go():
        sess, b, brain, calls = _session(["Junie likes snow angels"])
        await sess.call()
        await wait_mic_open(sess)
        await sess.set_child("Juniper")
        await _turn(sess, 1)
        assert sess.active == "Juniper"
        await until(lambda: calls == [("Juniper", "Junie likes snow angels")])
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


def test_p4_4_a_quiet_turn_is_still_answered():
    """No loudness-based dropping: a turn the voice detector accepts is answered however quiet it was."""
    async def go():
        sess, b, brain, calls = _session(["I want a red truck"])
        await sess.call()
        await wait_mic_open(sess)
        await sess.set_child("Juniper")
        from test_stage_h import pcm
        await sess.audio_in(pcm(0.2, False) + pcm(1.0, True) + pcm(2.0, False))
        await until(lambda: len(sess.metrics) == 1)
        assert sess.counters["turns"] == 1
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())


@pytest.mark.parametrize("text,mentioned", [
    ("Wren, wait your turn.", {"Wren": 1}), ("Wren's puppy is called Biscuit", {"Wren": 1}),
    ("Junie and Wren", {"Juniper": 1, "Wren": 1}), ("I like snow", {}), ("Emmanuel wrenches", {}),
])
def test_p4_4_mentioned_names_counts_possessives_and_nicknames(text, mentioned):
    from santa.web.session import mentioned_names
    assert mentioned_names(text, NAMES, ALIASES) == mentioned


def test_p4_4_a_story_about_another_childs_pet_is_not_stored_for_the_active_child():
    async def go():
        sess, b, brain, calls = _session(["Wren's puppy is called Biscuit"])
        await sess.call()
        await wait_mic_open(sess)
        await sess.set_child("Juniper")
        await _turn(sess, 1)
        assert sess.active == "Juniper"
        assert calls == []
        await sess.hangup()
        await wait_state(sess, State.IDLE)
    asyncio.run(go())
