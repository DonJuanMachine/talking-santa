"""P1-3 (review pass 1): the gift-promise net missed common toddler gifts, the child's name in place of "you", other
verbs and modals, and "Yes! A pony for you!". Invariant I3: Santa never promises a specific gift.

Part A widens the word-level rules in santa/spec.py. The gate stays remove-only: a promise sentence and everything
after it are not spoken (FALLBACK if nothing came before). The child's name (and registered nicknames) is passed to
the gate by the caller; no name is hard-coded. Fixture names only.
"""
import pytest

from santa import spec, speech

FB = spec.FALLBACK

GIFT_WORDS = ["bunny", "kitty", "doggy", "dollhouse", "Barbie", "fire engine", "play kitchen", "book", "iPad",
              "Paw Patrol tower"]
MUST_STOP_GIFT_WORDS = ([f"I'll bring you a {g}!" for g in GIFT_WORDS if g != "iPad"]
                        + ["I'll bring you an iPad!", "I'll bring you crayons!", "I'll bring you some blocks!",
                           "I'll bring you slime!", "I'll bring you a baby doll!", "I'll bring you two kitties!"])
MUST_STOP_NAME = ["I'll bring Emma a bike!", "Emma will get a bike!", "Emma's getting a bike from Santa!",
                  "I'll bring a bike for Emma!", "Emma is going to get a puppy!", "Emma'll get a pony!"]
MUST_STOP_VERBS = [
    "You're gonna get a bike!", "You are gonna get a bike!", "You will have a puppy!",
    "Of course you can have a pony!", "You can have the truck!", "I can bring you a bike!",
    "I could bring you a bike!", "I'll surprise you with a puppy!", "I'll drop off a scooter at your house!",
    "There will be a puppy under your tree!", "Your new bike will be under the tree!",
    "My elves are building you a train right now!",
    "I will definitely, absolutely, for sure bring you a bike!",
    "Santa can bring you a puppy!",
]
MUST_STOP_TWO = ["Yes! A pony for you!", "Yes, a pony for you!", "Of course! A shiny red bike just for you!"]

# Ordinary talk that must stay spoken (no gift, no recipient, a question, a negation, or Santa's own things).
MUST_SPEAK_A = [
    "Yes!", "Yes, you can!", "Yes, I love that idea!", "Santa wants to hear all about it!",
    "A pony sounds wonderful, and the reindeer love ponies too!", "Yes, I'll bring a smile to everyone!",
    "You can have fun with your new friends!", "You can have so much fun in the snow!",
    "Can you give your teddy a hug for me?", "Can you bring your book to show me?",
    "I can't bring you a pony, but I'll tell my elves!", "I can see you love your kitty!",
    "I'll read you a story!", "I'll put your name on my nice list!", "There will be snow at the North Pole!",
    "Your puppy will be so happy to see you!", "The elves are making toys!", "I'll tell my elves about the bunny!",
    "Do you like books?", "What would you like Santa to bring you?", "I love reading a good book by the fire!",
    "Do you play with blocks?", "You can find the North Star in the sky!",
    "Yes! Do you want a pony?", "Yes! The reindeer love ponies!",
]
# With the child's name passed to the gate: a vocative or the name as a subject of something else stays spoken.
MUST_SPEAK_NAME = ["Emma, the elves will make toys all night long!", "Emma, do you want a bike?",
                   "I'm so happy to see you, Emma!", "Emma will get so big this year!",
                   "Emma's puppy sounds so sweet!", "I'll make you smile, Emma!"]


@pytest.mark.parametrize("bad", MUST_STOP_GIFT_WORDS + MUST_STOP_VERBS + MUST_STOP_TWO)
def test_p1_3a_promise_is_stopped(bad):
    g = speech.filter_reply(bad)
    assert g.reason == "promise", (bad, g.text)
    assert g.text in (FB, "Yes!", "Of course!")          # the "Yes!" of a two-sentence promise was already spoken


@pytest.mark.parametrize("bad", MUST_STOP_GIFT_WORDS + MUST_STOP_VERBS)
def test_p1_3a_promise_after_a_safe_sentence_is_never_spoken(bad):
    g = speech.filter_reply("Hi Emma! " + bad + " Do you like snow?")
    assert g.text == "Hi Emma!" and g.reason == "promise"


@pytest.mark.parametrize("bad", MUST_STOP_NAME)
def test_p1_3a_the_childs_name_in_place_of_you_is_a_promise(bad):
    assert spec.safety_reason(bad, names=("Emma",)) == "promise"
    g = speech.filter_reply("Ho ho ho! " + bad, names=["Emma"])
    assert g.text == "Ho ho ho!" and g.reason == "promise"


def test_p1_3a_a_registered_nickname_counts_like_the_name():
    assert spec.safety_reason("I'll bring Wren a bike!", names=("Juniper", "Wren")) == "promise"
    assert spec.safety_reason("Wren's getting a puppy!", names=("Juniper", "Wren")) == "promise"


def test_p1_3a_no_name_is_hard_coded():
    """Only the names the caller passes count: another child's name, or no name, is not "you"."""
    assert spec.safety_reason("I'll bring Emma a bike!") is None
    assert spec.safety_reason("I'll bring Emma a bike!", names=("Leo",)) is None
    assert speech.filter_reply("Emma will get a bike!").reason is None


@pytest.mark.parametrize("ok", MUST_SPEAK_A)
def test_p1_3a_ordinary_talk_stays_spoken(ok):
    assert spec.safety_reason(ok) is None
    assert speech.filter_reply(ok).text == ok


@pytest.mark.parametrize("ok", MUST_SPEAK_NAME)
def test_p1_3a_the_name_alone_does_not_make_a_promise(ok):
    assert spec.safety_reason(ok, names=("Emma",)) is None
    assert speech.filter_reply(ok, names=["Emma"]).text == ok


def test_p1_3a_names_with_regex_characters_are_matched_literally():
    assert spec.safety_reason("I'll bring Mary-Kate a bike!", names=("Mary-Kate",)) == "promise"
    assert spec.safety_reason("I'll bring Emma a bike!", names=("(.*)",)) is None
    assert spec.safety_reason("Hi there!", names=("", "  ")) is None


def test_p1_3a_two_sentence_promise_only_with_an_affirmative_and_for_you():
    assert speech.filter_reply("Yes! A pony is a lovely animal!").text == "Yes! A pony is a lovely animal!"
    assert speech.filter_reply("I love snow! A pony for you!").reason is None   # no affirmative before it


@pytest.mark.parametrize("text", ["I will " + "very " * 3000 + "x", "I can " + "-" * 5000 + "x",
                                  "There will be " + "-" * 5000 + "x", "Yes! " + "big " * 3000 + "x",
                                  "Your " + "big " * 3000 + "x"])
def test_p1_3a_new_patterns_stay_fast(text):
    import time
    t0 = time.perf_counter()
    spec.safety_reason(text, names=("Emma",))
    assert time.perf_counter() - t0 < 0.5


@pytest.mark.parametrize("bad", ["The elves are making a doll for you!", "The elves are wrapping your new bike!",
                                 "My elves are making extra toys for you right now in the workshop."])
def test_p1_3a_making_with_a_recipient_is_a_promise(bad):
    assert spec.safety_reason(bad) == "promise"


def test_p1_3a_making_without_a_recipient_stays_spoken():
    """Golden corpus (ministral3_14B): the "you" belongs to the next clause, after a dash."""
    ok = ("My elves are making special cat toys right now—do you think Mittens would like a little red ball?")
    assert spec.safety_reason(ok) is None
    assert spec.safety_reason("I'm building Emma a train!", names=("Emma",)) == "promise"


def test_p1_3a_first_person_progressive_is_a_promise():
    assert spec.safety_reason("I'm bringing you a pony!") == "promise"
    assert spec.safety_reason("I am making you a dollhouse!") == "promise"
    assert spec.safety_reason("I'm bringing my sleigh!") is None


# ------------------------------------------------------------------ the app passes the active child's names
def _santa(reply, monkeypatch, tmp_path):
    from _support import FakeClient
    from santa import brain, memory
    real_save = memory.save
    monkeypatch.setattr(memory, "save", lambda profiles, path=tmp_path / "p.json": real_save(profiles, path))
    s = brain.Santa(model="fake", client=FakeClient([reply]),
                    profiles={"Juniper": {"age": 4, "facts": [], "nicknames": ["Wren"]}, "Leo": {"age": 3, "facts": []}})
    s.last_ok_time = brain._now()
    return s


@pytest.mark.parametrize("reply", ["Hello there! I'll bring Juniper a bike!", "Hello there! Wren's getting a puppy!"])
def test_p1_3a_brain_passes_the_active_childs_name_and_nicknames(reply, monkeypatch, tmp_path):
    s = _santa(reply, monkeypatch, tmp_path)
    assert s.reply("Juniper", "hi santa") == "Hello there!"
    assert s.last_reply.reason == "blocklist:promise"      # the Reply code for a promise stop (brain._reason_code)


def test_p1_3a_brain_does_not_use_another_childs_name(monkeypatch, tmp_path):
    s = _santa("Hello there! I'll bring Juniper a bike!", monkeypatch, tmp_path)
    assert s.reply("Leo", "hi santa") == "Hello there! I'll bring Juniper a bike!"
