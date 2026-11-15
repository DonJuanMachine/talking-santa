"""P1-3 Part B (review pass 1): after the child asks for a gift, Santa's pronoun answer is the promise ("I'll bring
it!", "Yes! You'll find it under the tree!"). Invariant I3: Santa never promises a specific gift.

Decided in notes/review/plans/p1-3-part-b-plan.md: Option 2 and trigger (b).
- A gift turn = the child's own words (never Santa's gift-ask note): gifts.talks_gifts, a request shape
  ("Can I have ...?", "Will you bring me ...?", "I really want ...") or a gift noun ("A pony!").
- On a gift turn only: rules B1 (pronoun object / you-subject), B2 (bare "Yes, I will!") and B3 (affirmative +
  commitment + gift noun), never on a question; and a sentence that is only an affirmative ("Yes!") is held for one
  sentence: dropped with a promise that follows, spoken with a harmless one, dropped if the reply ends on it.
- The gate stays remove-only and prefix-only, and every chunking of a reply gives the same result (S11).
Fixture names only.
"""
import pytest

from santa import spec, speech

FB = spec.FALLBACK
CHUNKS = [None, 1, 3]
GIFT_ASK = "Can I have a pony?"


def heard(raw, child=None, chunk=None, names=()):
    """(heard text, reason): the whole reply at once (chunk None) or streamed in chunks of `chunk` characters."""
    if chunk is None:
        g = speech.filter_reply(raw, names=names, child_turn=child)
    else:
        g = speech.Gate(names=names, child_turn=child)
        for s in speech.sentences_from_stream([raw[i:i + chunk] for i in range(0, len(raw), chunk)]):
            g.push(s)
            if g.stopped:
                break
        g.finish()
    return g.text, g.reason


def assert_prefix(raw, text):
    """Remove-only, prefix-only: what is heard is the first k cleaned sentences (or FALLBACK)."""
    sents = spec.split_clean(raw)
    assert text == FB or any(text == " ".join(sents[:k]) for k in range(1, len(sents) + 1)), (raw, text)


# ------------------------------------------------------------------ the trigger: the child's words only
@pytest.mark.parametrize("child", [
    "I want a pony for Christmas!", "Will you bring me a bike?", "Can I have a pony?", "Could I get a puppy please?",
    "I really want a doll", "A pony!", "can I please have a kitty", "May I get a scooter?", "Can you give me a robot?",
    "I need a new bike", "I wish for a puppy", "I want to sing a song", "a dollhouse",
])
def test_p1_3b_gift_turn_trigger(child):
    assert speech.is_gift_turn(child)


@pytest.mark.parametrize("child", ["hi santa", "do you remember my cat?", "what do reindeer eat?", "I like snow",
                                   "tell me a joke", "my name is Juniper", "", None])
def test_p1_3b_not_a_gift_turn(child):
    assert not speech.is_gift_turn(child)


# ------------------------------------------------------------------ pronoun promises after a gift request: stopped
MUST_STOP_FALLBACK = [
    # the finding's pronoun examples
    "Yes, I'll bring you one!", "I'll bring it!", "I'll bring that for you!", "I'll put one in your stocking!",
    "Yes! You'll find it under the tree!", "I wrote it down, and you'll get it!",
    # the plan's examples (B1, B2, B3 and the held affirmative)
    "Of course! I'll bring it!", "Okay! You'll get one!", "Yes! A pony for you!", "Yes, I will!", "Yes, you can!",
    "Of course! I'll bring a pony!", "Sure! My elves will make one!", "You can have one!",
    "Yes! You're gonna get it!", "Santa will bring you that!", "We're going to bring you one!",
    "Ho ho ho, yes! I'll bring it!", "Yes! Yes! I'll bring it!",
]


@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("bad", MUST_STOP_FALLBACK)
def test_p1_3b_pronoun_promise_after_a_gift_request_gives_fallback(bad, chunk):
    text, reason = heard(bad, GIFT_ASK, chunk)
    assert (text, reason) == (FB, "promise"), bad


@pytest.mark.parametrize("chunk", CHUNKS)
def test_p1_3b_yes_you_will_find_it_child_hears_nothing_of_it(chunk):
    assert heard("Yes! You'll find it under the tree!", "Can I have a pony?", chunk) == (FB, "promise")


@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("raw,expect", [
    ("What a lovely idea! I'll bring it!", "What a lovely idea!"),
    ("Ho ho ho! Yes! You'll find it under the tree!", "Ho ho ho!"),
    ("A pony! Yes! I'll bring you one! Do you like snow?", "A pony!"),
    ("I love ponies! Of course! I'll bring a pony!", "I love ponies!"),
])
def test_p1_3b_promise_after_a_spoken_sentence_keeps_only_that_sentence(raw, expect, chunk):
    assert heard(raw, GIFT_ASK, chunk) == (expect, "promise")


@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("child", [GIFT_ASK, "I want a pony", "A pony!", "Will you bring me a pony?"])
def test_p1_3b_affirmative_then_harmless_is_spoken_whole(child, chunk):
    raw = "Yes! The reindeer love ponies!"
    assert heard(raw, child, chunk) == (raw, None)


@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("raw,expect", [
    ("Yes!", FB), ("Of course!", FB), ("Ho ho ho, yes!", FB), ("Okay! Sure!", FB),
    ("That sounds lovely! Yes!", "That sounds lovely!"), ("Ho ho ho! Of course!", "Ho ho ho!"),
    ("Yes, Juniper!", FB),
])
def test_p1_3b_reply_ending_on_a_held_affirmative_drops_it(raw, expect, chunk):
    assert heard(raw, GIFT_ASK, chunk, names=("Juniper",))[0] == expect


# ------------------------------------------------------------------ the extra item: Part A's wider window
MAKE_FOR_YOU = "I'll tell my elves to make that whoosh, a big, red truck just for you"


@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("child", ["i want a big red truck", "hi santa", None])
def test_p1_3b_make_that_just_for_you_is_stopped_on_any_turn(child, chunk):
    assert spec.safety_reason(MAKE_FOR_YOU) == "promise"
    assert heard(MAKE_FOR_YOU, child, chunk) == (FB, "promise")


# ------------------------------------------------------------------ must stay spoken
MUST_SPEAK_GIFT_TURN = [
    "Yes, I love that idea!", "Santa wants to hear all about it!",
    "A pony sounds wonderful, and the reindeer love ponies too!", "What would you like Santa to bring you?",
    "Will you share it with your friends?", "Can you bring it to show me?", "Do you want me to bring one?",
    "Ho ho ho! A pony! What color would it be?", "I'll make it snow at the North Pole!",
    "Yes! Santa will think about it!", "Ponies are so much fun! What would you name it?",
]


@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("ok", MUST_SPEAK_GIFT_TURN)
def test_p1_3b_gift_turn_ordinary_talk_stays_spoken(ok, chunk):
    assert heard(ok, GIFT_ASK, chunk) == (ok, None)


@pytest.mark.parametrize("chunk", CHUNKS)
def test_p1_3b_bring_a_smile_after_a_non_gift_turn_stays_spoken(chunk):
    ok = "Yes, I'll bring a smile to everyone!"
    assert heard(ok, "do you like snow?", chunk) == (ok, None)


ORDINARY_TURNS = ["hi santa", "do you remember my cat?", "what do reindeer eat?", "I like snow", "tell me a joke",
                  None, ""]
REPLIES = ["Yes!", "Yes, you can!", "Yes, I will!", "Yes! You'll find it under the tree!", "I'll bring it!",
           "Of course! I'll bring a pony!", "That sounds lovely! Yes!", "Ho ho ho! Hello there, Juniper!",
           "You know what?", "Yes! A pony for you!", "My number is 555. 123. 4567. Bye!"]


@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("child", ORDINARY_TURNS)
def test_p1_3b_a_non_gift_turn_behaves_exactly_as_before(child, chunk):
    for raw in REPLIES:
        before = speech.filter_reply(raw, names=("Juniper",))
        assert heard(raw, child, chunk, names=("Juniper",)) == (before.text, before.reason), (child, raw)


# ------------------------------------------------------------------ remove-only, prefix-only, fast
@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("raw", MUST_STOP_FALLBACK + MUST_SPEAK_GIFT_TURN + REPLIES)
def test_p1_3b_gift_turn_output_is_a_prefix(raw, chunk):
    assert_prefix(raw, heard(raw, GIFT_ASK, chunk)[0])


@pytest.mark.parametrize("text", ["Yes! " + "very " * 3000 + "x", "I'll " + "-" * 5000 + " it",
                                  "Yes, " + "I " * 3000 + "will", "You'll " + "big " * 3000 + "it"])
def test_p1_3b_new_patterns_stay_fast(text):
    from _timed import timed     # a child process, killed after a few seconds: a catastrophic pattern fails, not hangs
    times = timed([("safety_reason", text, {"names": ["Juniper"], "gift_turn": True}), ("is_gift_turn", text, {})])
    assert sum(dt for dt, _ in times) < 0.5


# ------------------------------------------------------------------ the app passes the child's words
def _santa(reply, monkeypatch, tmp_path, chunk):
    from _support import FakeClient
    from santa import brain, memory
    real_save = memory.save
    monkeypatch.setattr(memory, "save", lambda profiles, path=tmp_path / "p.json": real_save(profiles, path))
    s = brain.Santa(model="fake", client=FakeClient([reply], chunk=chunk),
                    profiles={"Juniper": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": []}})
    s.last_ok_time = brain._now()
    return s


@pytest.mark.parametrize("chunk", [1, 3, 50])
def test_p1_3b_brain_uses_the_childs_request(chunk, monkeypatch, tmp_path):
    s = _santa("Yes! You'll find it under the tree!", monkeypatch, tmp_path, chunk)
    assert s.reply("Juniper", "Can I have a pony?") == FB
    assert s.last_reply.reason == "blocklist:promise"


@pytest.mark.parametrize("chunk", [1, 3, 50])
def test_p1_3b_brain_non_gift_turn_unchanged(chunk, monkeypatch, tmp_path):
    """Records an accepted trade-off, not a desired outcome: after a non-gift turn the pronoun promise is spoken,
    because the pronoun rules run only on a recognised gift turn (P7-1; 0 promise-like sentences in 182 short
    conversations on e4b, persona v1). See test_accepted_gate_gaps.py and CHANGELOG.md "Known open items"."""
    s = _santa("Yes! You'll find it under the tree!", monkeypatch, tmp_path, chunk)
    assert s.reply("Juniper", "I like snow") == "Yes! You'll find it under the tree!"


@pytest.mark.parametrize("chunk", [1, 3])
def test_p1_3b_brain_ignores_santas_gift_ask_note(chunk, monkeypatch, tmp_path):
    """The gift-ask note goes on the model's copy of the turn; the gate reads only the child's words."""
    from santa import gifts
    s = _santa("Yes! You'll find it under the tree!", monkeypatch, tmp_path, chunk)
    s.gifts = gifts.Gifts()
    monkeypatch.setattr(s.gifts, "note", lambda *a, **k: " (ask: what gift or present do you want? I want a pony)")
    assert s.reply("Juniper", "I like snow") == "Yes! You'll find it under the tree!"
