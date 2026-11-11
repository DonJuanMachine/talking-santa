"""Songs (2026-11-10): a song request gets a real first verse from fixed text; no model call; Santa never offers songs."""
import _support  # noqa: F401  (temp profiles; must come first)

import pytest

from santa import persona, songs, spec, speech
from test_time_and_gifts import Fake, santa, say  # noqa: F401  (same fake client and helpers)


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    for k in ("SANTA_ARC", "SANTA_GIFT_ASK", "SANTA_TIME_NOTE", "SANTA_GENTLE", "SANTA_SONGS"):
        monkeypatch.delenv(k, raising=False)


def run(s, speaker, text):
    return list(s.reply_stream(speaker, text))


@pytest.mark.parametrize("text", ["can you sing jingle bells", "Santa, sing a song!", "sing", "please sing",
                                  "will you sing for me", "sing me a song", "I want a song", "can I hear a song",
                                  "deck the halls", "sing another one", "could santa sing"])
def test_asks_for_song_yes(text):
    assert songs.asks_for_song(text)


@pytest.mark.parametrize("text", ["I sang at school", "I like singing", "my sister sings", "the song was fun",
                                  "we have a tree", "hi santa"])
def test_asks_for_song_no(text):
    assert not songs.asks_for_song(text)


@pytest.mark.parametrize("key", list(songs.SONGS))
@pytest.mark.parametrize("gentle", [False, True])
def test_every_line_passes_the_canned_rules_and_safety(key, gentle):
    for line in songs.lines(key, gentle):
        assert spec.safety_reason(line) is None, line
        heard, why = speech.sanitize_ex(line)
        assert why is None and heard == line, line


def test_full_first_verse_is_sung_without_a_model_call():
    s = santa()
    out = run(s, "Emma", "can you sing a song?")
    assert out[0] == "Here is Jingle Bells."   # no "Ho ho": Santa laughs only at the greeting, a song or a joke
    assert out[1:] == songs.SONGS["jingle"][1]
    assert s.client.requests == []                                   # no model call
    assert s.history[-1]["content"] == " ".join(out)
    assert s.last_reply.spoken == out and not s.last_reply.fallback


def test_named_song_and_taking_turns():
    s = santa()
    assert "Deck the Halls" in run(s, "Emma", "sing deck the halls")[0]
    assert "Jingle Bells" in run(s, "Emma", "sing another one")[0]   # first one not sung yet
    assert "Deck the Halls" in run(s, "Emma", "sing again")[0]       # then take turns
    assert "Jingle Bells" in run(s, "Leo", "can you sing jingle bells")[0]


def test_gentle_song_has_no_ho_ho_ho():
    s = santa()
    say(s, "Emma", "my dog died")
    assert run(s, "Emma", "can you sing")[0] == "Here is Jingle Bells."


def test_song_turn_counts_for_the_trackers():
    s = santa()
    for i in range(4):
        say(s, "Emma", f"snow {i}")
    run(s, "Emma", "sing a song")                                    # turn 5 is the song
    assert s.gifts.state("Emma").turns == 5


def test_caller_stopping_early_still_records_the_turn():
    s = santa()
    g = s.reply_stream("Emma", "sing a song")
    next(g)
    g.close()                                                        # hang up after the first line
    assert s.history[-1] == {"role": "assistant", "content": "Here is Jingle Bells."}


def test_off_switch(monkeypatch):
    monkeypatch.setenv("SANTA_SONGS", "0")
    s = santa()
    run(s, "Emma", "can you sing a song?")
    assert len(s.client.requests) == 1                               # the model answers instead


def test_system_prompt_forbids_song_offers_and_keeps_persona_v1():
    s = santa()
    sp = s.system_prompt()
    assert sp.startswith(persona.SANTA_PROMPT.split("{kids_block}")[0])
    assert sp.endswith(persona.PROMPT_ADDITIONS) and "Never offer to sing a song" in sp


# ------------------------------------------------------------------------------------- a song Santa does not know
@pytest.mark.parametrize("text,status", [("can you sing rudolph the red nosed reindeer", "unknown"),
                                         ("sing frosty the snowman", "unknown"), ("sing silent night", "unknown"),
                                         ("sing a christmas song", "none"), ("sing me a song please", "none"),
                                         ("can you sing", "none"), ("sing jingle bells", "known"),
                                         ("sing deck the halls for me", "known")])
def test_title_status(text, status):
    assert songs.title_status(text) == status


@pytest.mark.parametrize("key", list(songs.SONGS))
@pytest.mark.parametrize("gentle", [False, True])
def test_offer_lines_pass_the_canned_rules_and_safety(key, gentle):
    for line in songs.offer_lines(key, gentle):
        assert spec.safety_reason(line) is None, line
        heard, why = speech.sanitize_ex(line)
        assert why is None and heard == line, line


def test_unknown_song_offer_then_yes_sings_it():
    s = santa()
    out = run(s, "Emma", "can you sing frosty the snowman")
    assert out == ["I don't know that one.", "But I know Jingle Bells! Would you like to hear it?"]
    assert s.client.requests == []
    out = run(s, "Emma", "yes please")
    assert out[0] == "Here is Jingle Bells." and out[1:] == songs.SONGS["jingle"][1]
    assert s.client.requests == []


def test_unknown_song_offer_then_naming_the_other_song():
    s = santa()
    run(s, "Emma", "sing silent night")
    assert "Deck the Halls" in run(s, "Emma", "deck the halls")[0]


def test_offer_lasts_one_turn_and_no_means_chat():
    s = santa()
    run(s, "Emma", "sing silent night")
    run(s, "Emma", "no thank you")                                   # the model answers
    assert len(s.client.requests) == 1
    run(s, "Emma", "yes")                                            # offer expired: the model answers again
    assert len(s.client.requests) == 2


def test_offer_is_only_for_the_child_who_asked():
    s = santa()
    run(s, "Emma", "sing silent night")
    run(s, "Leo", "yes")
    assert len(s.client.requests) == 1                               # Leo's yes is not an answer to Emma's offer


def test_offer_after_a_song_offers_a_different_one():
    s = santa()
    run(s, "Emma", "sing jingle bells")
    assert "Deck the Halls" in run(s, "Emma", "sing frosty")[1]


@pytest.mark.parametrize("gentle", [False, True])
def test_rudolph_gets_his_own_answer(gentle):
    out = songs.offer_lines("jingle", gentle, "can you sing rudolph the red nosed reindeer")
    assert "Rudolph is one of my reindeer! I don't know his song." in out[0]
    assert not out[0].startswith("Ho ho")        # never, gentle or not (ho_once)
    for line in out:
        heard, why = speech.sanitize_ex(line)
        assert why is None and heard == line and spec.safety_reason(line) is None


def test_rudolph_in_a_call():
    s = santa()
    out = run(s, "Emma", "sing rudolph")
    assert out == ["Rudolph is one of my reindeer! I don't know his song.",
                   "But I know Jingle Bells! Would you like to hear it?"]
