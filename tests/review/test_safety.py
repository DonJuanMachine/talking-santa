"""Review tests for santa/safety.py. xfail(strict=True) = confirmed bug on current code."""
import pytest

from santa import safety

FALLBACK = safety.FALLBACK


# ------------------------------------------------------------------ _clean
@pytest.mark.parametrize("raw,must_keep", [
    ("It's **not** your fault.", "not"),
    ("Don't worry, the dark is **never** scary!", "never"),
    ("Thunder is **not** scary at all, Leo.", "not"),
    ("You're a **star**!", "star"),
])
def test_bold_markdown_keeps_word(raw, must_keep):
    out = safety.sanitize(raw)
    assert must_keep in out.lower(), out   # current: "It's your fault." / "You're a!"


def test_multiword_emphasis_negation_kept():
    out = safety.sanitize("That is *not at all* scary.")
    assert "not" in out.lower(), out          # current output: "That is scary."


def test_single_emphasis_word_kept_ALREADY_FIXED():
    # verifies the "keep *big*" fix, including punctuation/apostrophes next to the asterisk
    assert safety._clean("That's *so* cool!") == "That's so cool!"
    assert safety._clean("it's *big*!") == "it's big!"
    assert safety._clean("*Emma's* cat") == "Emma's cat"
    assert safety._clean("*Mittens*? What a name!") == "Mittens? What a name!"
    assert safety._clean("I love *big*, *red* trucks") == "I love big, red trucks"
    assert safety._clean("_big_ truck") == "big truck"


def test_known_action_words_removed_ALREADY_FIXED():
    assert safety._clean("*waves* Hi Emma!") == "Hi Emma!"
    assert safety._clean("*chuckles* Ho ho") == "Ho ho"
    assert safety._clean("*waves happily* Hi Emma!") == "Hi Emma!"
    assert safety._clean("Ho ho ho! (giggles) Hi Emma!") == "Ho ho ho! Hi Emma!"


@pytest.mark.parametrize("raw", ["Mommy laughs!", "Santa smiles.", "Emma smiles! That's lovely."])
def test_bare_action_rule_keeps_real_sentences(raw):
    assert safety._clean(raw) == raw


def test_bracket_content_kept():
    assert "surprise" in safety._clean("You get [a surprise]!")


@pytest.mark.parametrize("raw", ["Hi ⭐ Emma!", "Hi 🧑‍🎄 Emma!", "Snow ❄️ fun"])
def test_emoji_fully_removed(raw):
    out = safety._clean(raw)
    assert all(ord(c) < 0x2000 for c in out), repr(out)


# ------------------------------------------------------------------ _truncate
def test_truncate_handles_abbreviations():
    out = safety.sanitize("Mr. Snowman is here. Dr. Elf says hi! I love you. Bye.")
    assert not out.endswith("Dr."), out


def test_truncate_does_not_end_on_setup_line():
    raw = "Ho ho ho! Hi Emma! You know what? The elves are making something special just for you."
    assert not safety.sanitize(raw).endswith("You know what?")


def test_word_cap_applies():
    # B2 (TEST_CHANGES.md): the cap only stops at a sentence boundary and never invents "!"; one 81-word sentence
    # cannot be cut at a boundary, so it is the fallback.
    out = safety.sanitize(" ".join(["snow"] * 80) + ".")
    assert len(out.split()) <= 45 and out == FALLBACK


# ------------------------------------------------------------------ BLOCKLIST
def test_grief_reply_not_replaced_by_cheerful_fallback():
    raw = "Oh, Ziv, your goldfish is dead? That is so sad. Let's tell your mommy together."
    out = safety.sanitize(raw)
    assert "favorite animal" not in out, out   # FALLBACK asks about a favorite animal


@pytest.mark.parametrize("raw", ["A killer whale says hi!", "I'll die of laughter, Leo!", "My bloodhound loves snow."])
def test_blocklist_no_false_positive(raw):
    assert safety.sanitize(raw) != FALLBACK


@pytest.mark.parametrize("raw", [
    "You're on Santa's naughty list!",
    "You might end up on the naughty list.",
    "The elves have toy guns.",
    "I'll bring you a puppy!",
    "You will get a pony!",
])
def test_blocklist_catches_variants(raw):
    assert safety.sanitize(raw) == FALLBACK


@pytest.mark.parametrize("raw", ["Okay! I am ChatGPT!", "I'm Gemma, made by Google!", "I'm a robot, Ziv."])
def test_ai_identity_blocked(raw):
    if raw.startswith("Okay! "):   # a safe sentence comes first: it may be spoken, the claim never (TEST_CHANGES.md)
        _assert_claim_never_spoken(raw)
        return
    assert safety.sanitize(raw) == FALLBACK

def _assert_claim_never_spoken(raw, rule="ai_identity"):
    """Safety decision at the Stage B gate (TEST_CHANGES.md): a sentence that trips a SAFETY rule is never spoken and
    nothing after it is; a safe sentence BEFORE it may be ("Okay! I am ChatGPT!" -> "Okay!"); the reason is recorded."""
    from santa import spec, speech
    gate = speech.filter_reply(raw)
    assert gate.reason == rule, gate.reason
    assert gate.text == safety.FALLBACK or (raw.startswith(gate.text) and spec.safety_reason(gate.text) is None
                                            and spec.safety_reason(raw[len(gate.text):].strip()) == rule), gate.text



def test_flat_denial_passes_by_design():
    # Documents current behavior (not marked as a bug): a denial is spoken as-is.
    # Ministral 8B produced "And I'm not an AI, I'm t..." in the benchmark.
    assert safety.sanitize("No, I'm not a computer, I'm real!") == "No, I'm not a computer, I'm real!"


# ------------------------------------------------------------------ PRIVATE_RE
def test_small_numbers_not_redacted():
    # Refutes the suspicion: separate small numbers with words between them are fine.
    s = "I'm 4 and I have 3 cats and 2 dogs"
    assert safety.redact_private(s) == s


@pytest.mark.parametrize("s", ["1 2 3 4 5 6 7", "I can count! 1 2 3 4 5 6 7 8 9 10"])
def test_counting_not_redacted(s):
    assert safety.redact_private(s) == s


@pytest.mark.parametrize("s", [
    "I live at 42 Maple Way",
    "my house is 7 Elm Blvd",
    "I live at forty two Maple Street",
    "my mommy's phone is five five five one two one two",
    "my house number is 1234",
])
def test_private_detail_redacted(s):
    assert safety.redact_private(s) != s


def test_output_address_not_spoken():
    out = safety.sanitize("Ho ho! I know your house, 12 Oak Lane!")
    assert "12 Oak Lane" not in out, out
