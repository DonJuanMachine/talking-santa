"""Regression tests added with the fixes for santa/safety.py (not part of the original review)."""
import pytest

from santa import safety


def test_one_question_keeps_all_sentences_and_last_question():
    # B2/decision 2 (TEST_CHANGES.md): nothing is demoted any more; all sentences (and both questions) are kept as-is
    raw = "Mittens, you said? I remember her! Do you like lights?"
    assert safety.sanitize(raw) == raw


def test_one_question_never_truncates_at_first_question_mark():
    raw = "A puppy? Ho ho! What is his name?"
    assert safety.sanitize(raw) == raw   # B2/decision 2: never cut at the first "?", never demoted


def test_check_still_reports_multiple_questions_on_raw_text():
    # check() was deleted (B1); the measurement now lives in spec.shape_flags (see docs/history/TEST_CHANGES.md)
    from santa import spec
    assert "questions>1" in spec.shape_flags("What? Why?")


def test_fallback_is_neutral_and_passes_its_own_filters():
    assert safety.FALLBACK == "Santa is listening. Can you tell your grown-up too?"   # no "Ho ho" (ho_once)
    assert safety.sanitize(safety.FALLBACK) == safety.FALLBACK


@pytest.mark.parametrize("raw", ["It's *not* ok.", "That is __never__ true.", "Not ***ever***!"])
def test_negations_survive_all_emphasis_styles(raw):
    out = safety.sanitize(raw)
    assert any(w in out.lower() for w in ("not", "never", "ever")), out
    assert "*" not in out and "_" not in out


def test_asterisk_span_of_ordinary_words_is_never_deleted():
    assert "castle" in safety._clean("We saw *a big castle* today.")


@pytest.mark.parametrize("raw,expected", [
    ("*waves happily* Hi!", "Hi!"),
    ("*jingle softly* Hi!", "Hi!"),
    ("Ho ho giggles! Hi.", "Ho ho! Hi."),
    ("Giggles. Hi Emma!", "Hi Emma!"),
])
def test_stage_directions_still_removed(raw, expected):
    assert safety._clean(raw) == expected


def test_parentheses_with_real_words_are_kept():
    assert "big feeling" in safety._clean("It's okay (that's a big feeling) Leo.")


@pytest.mark.parametrize("raw", ["Snow ⭐❤️ time", "Hi 👨‍👩‍👧 all"])
def test_more_emoji(raw):
    out = safety._clean(raw)
    assert all(ord(c) < 0x2000 for c in out), repr(out)


@pytest.mark.parametrize("raw", ["I like Dr. Seuss and Mr. Rogers. Do you?", "We met Mrs. Claus. She said hi. Bye."])
def test_abbreviations_do_not_end_reply(raw):
    out = safety.sanitize(raw)
    assert not out.rstrip().endswith(("Dr.", "Mr.", "Mrs.")), out


@pytest.mark.parametrize("s", ["one two three four five six", "five four three two one", "10 11 12 13 14 15 16"])
def test_counting_in_words_or_down_not_redacted(s):
    assert safety.redact_private(s) == s


@pytest.mark.parametrize("s", ["call 555-123-4567", "(555) 123 4567", "my phone is 5551234567"])
def test_phone_numbers_redacted_with_phone_message(s):
    out = safety.redact_private(s)
    assert out == safety.PHONE_MSG and "phone number" in out


def test_address_gets_address_message():
    assert safety.redact_private("I live at 42 Maple Way") == safety.ADDRESS_MSG


@pytest.mark.parametrize("s", ["That is one special place!", "I have 3 cats and 12 dogs", "Santa has 9 reindeer on the sleigh"])
def test_ordinary_numbers_and_words_not_private(s):
    assert not safety.looks_private(s)
    assert safety.sanitize(s) == s


def test_private_output_returns_fallback_with_reason():
    assert safety.sanitize_ex("Call me at 555 123 4567") == (safety.FALLBACK, "private_output")
    assert safety.sanitize_ex("*waves*") == (safety.FALLBACK, "empty")
    assert safety.sanitize_ex("I promise a pony") == (safety.FALLBACK, "blocklist")
    assert safety.sanitize_ex("Hi Emma!") == ("Hi Emma!", None)


def test_last_name_is_private_fact_but_not_private_text():
    assert safety.looks_private_fact("last name is Johnson")
    assert not safety.looks_private("Santa does not need your last name")


def test_dead_end_and_laughing_not_blocked():
    assert safety.sanitize("This is a dead-end street for snowmen.") != safety.FALLBACK
    assert safety.sanitize("I'll die laughing, Ziv!") != safety.FALLBACK
