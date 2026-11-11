"""Review tests for santa/brain.py (fake client, temp profiles/transcripts)."""
import json

import pytest

from santa import config, safety

GREETING = "Ho ho ho! Merry Christmas! Who am I talking to?"


def _roles(call):
    return [m["role"] for m in call["messages"]]


def _assert_valid_roles(roles):
    assert roles[0] == "system"
    rest = roles[1:]
    assert rest and rest[0] == "user", roles
    assert rest[-1] == "user", roles
    for a, b in zip(rest, rest[1:]):
        assert a != b, f"two consecutive {a} turns: {roles}"


# ----------------------------------------------------------- history window
@pytest.mark.parametrize("with_greeting", [True, False])
def test_window_roles_always_valid_ALREADY_FIXED(make_santa, with_greeting):
    s = make_santa()
    if with_greeting:  # chat.py seeds history with an assistant greeting
        s.history.append({"role": "assistant", "content": GREETING})
    for i in range(30):
        s.reply("Emma", f"turn {i}")
    for call in s.client.santa_calls:
        _assert_valid_roles(_roles(call))
        assert len(call["messages"]) - 1 <= config.HISTORY_TURNS


def test_window_valid_after_model_errors(make_santa):
    s = make_santa(replies=[RuntimeError("boom"), "Hi!", RuntimeError("boom"), "Hi!"])
    s.history.append({"role": "assistant", "content": GREETING})
    for i in range(16):
        s.reply("Leo", f"turn {i}")
    for call in s.client.santa_calls:
        _assert_valid_roles(_roles(call))


def test_first_call_drops_greeting(make_santa):
    s = make_santa()
    s.history.append({"role": "assistant", "content": GREETING})
    s.reply("Emma", "hi santa")
    assert _roles(s.client.santa_calls[0]) == ["system", "user"]


def test_exception_in_reply_does_not_break_role_alternation(make_santa):
    s = make_santa(profiles={"Emma": ["has a cat"]})   # hand-edit typo in profiles.json
    with pytest.raises(AttributeError):
        s.reply("Emma", "hi")
    s.profiles = {"Emma": {"facts": []}}               # adult fixes it and carries on
    s.reply("Emma", "hi again")
    _assert_valid_roles(_roles(s.client.santa_calls[-1]))


# ----------------------------------------------------------- error handling
def test_model_error_is_visible(make_santa):
    s = make_santa(replies=[ConnectionError("model runner down")])
    out = s.reply("Emma", "hi santa")
    assert out == safety.FALLBACK                     # what the child hears
    assert s.last_stats.get("error"), s.last_stats    # nothing records the failure


def test_error_and_empty_stream_paths_return_fallback(make_santa):
    # Every path to FALLBACK: exception, empty stream, all-stage-direction reply, blocklisted reply.
    for reply in [RuntimeError("x"), "", "*waves*", "(giggles)", "I promise you a pony"]:
        s = make_santa(replies=[reply])
        assert s.reply("Emma", "hi") == safety.FALLBACK
    # An empty string is never returned to the caller.


def test_error_reports_zero_ttft(make_santa):
    s = make_santa(replies=[RuntimeError("x")])
    s.reply("Emma", "hi")
    assert s.last_stats["ttft"] == 0.0   # feeds into bench latency percentiles (see test_bench)


def test_client_has_short_timeout(tmp_profiles):
    from santa.brain import Santa
    s = Santa(model="fake", base_url="http://127.0.0.1:9/v1")
    assert s.client.timeout.read is not None and s.client.timeout.read <= 30, s.client.timeout


# ----------------------------------------------------------- memory plumbing
def test_extractor_does_not_see_santa_reply(make_santa):
    s = make_santa(replies=["Ho ho! I bet you love chocolate cookies, Emma!"])
    s.reply("Emma", "hi santa")
    s.remember("Emma", "hi santa")   # B3: extraction runs after the reply (TEST_CHANGES.md)
    prompt = s.client.extract_calls[0]["messages"][0]["content"]
    assert "chocolate cookies" not in prompt


def test_santa_invention_stored_as_child_fact(make_santa):
    # Documents the effect of B2 when the extractor model follows Santa's line.
    s = make_santa(replies=["Ho ho! I bet you love chocolate cookies, Emma!"],
                   extract='{"facts": ["loves chocolate cookies"]}')
    s.reply("Emma", "hi santa")
    s.remember("Emma", "hi santa")   # B3: extraction runs after the reply (TEST_CHANGES.md)
    assert "loves chocolate cookies" in s.profiles["Emma"]["facts"]


def test_redacted_turn_not_sent_to_extractor(make_santa):
    s = make_santa()
    s.reply("Emma", "my house is 42 Maple Street")
    s.remember("Emma", "my house is 42 Maple Street")   # B3: the extraction path is remember() (TEST_CHANGES.md)
    assert not s.client.extract_calls


def test_redaction_text_reaches_history_and_transcript(make_santa, tmp_profiles):
    s = make_santa()
    s.reply("Emma", "my phone is 555 123 4567")
    assert "555" not in json.dumps(s.history)
    assert "where they live" in s.history[0]["content"]  # says "where they live" even for a phone number
    s.save_transcript()
    files = list(config.TRANSCRIPT_DIR.glob("*.txt"))
    assert len(files) == 1 and "555" not in files[0].read_text()


def test_private_fact_not_saved_or_shared(make_santa, tmp_profiles):
    s = make_santa(extract='{"facts": ["lives at 42 Maple Way"]}')
    s.reply("Emma", "I live at 42 Maple Way")       # PRIVATE_RE misses "Way"
    s.remember("Emma", "I live at 42 Maple Way")     # B3: extraction after the reply (TEST_CHANGES.md)
    s.reply("Leo", "hi santa")
    s.remember("Leo", "hi santa")
    leo_prompt = " ".join(m["content"] for m in s.client.santa_calls[-1]["messages"])   # whole request, not only system
    saved = tmp_profiles.read_text()
    assert "Maple" not in saved and "Maple" not in leo_prompt


# ----------------------------------------------------------- speaker parsing
@pytest.mark.parametrize("line", ["Santa: say hi to everyone", "Yes: I want a truck", "Okay: bye"])
def test_parse_speaker_no_bogus_profiles(make_santa, line):
    s = make_santa()
    s.set_active("Emma")
    s.parse_speaker(line)
    assert set(s.profiles) == {"Emma", "Leo", "Ziv"}, set(s.profiles)


@pytest.mark.parametrize("line", ["Zoë: I have a dog named Rex", "Mary-Kate: I have a dog named Rex"])
def test_parse_speaker_non_ascii_name(make_santa, line):
    s = make_santa()
    s.set_active("Emma")
    speaker, _ = s.parse_speaker(line)
    assert speaker != "Emma"


def test_parse_speaker_case_insensitive_known_name(make_santa):
    s = make_santa()
    assert s.parse_speaker("emma: hi") == ("Emma", "hi")
    assert s.parse_speaker("no prefix here") == ("Emma", "no prefix here")
    assert s.parse_speaker("Emmanuel: hi")[0] == "Emmanuel"   # not merged into Emma


# ----------------------------------------------------------- transcript
def test_transcript_saved_to_configured_dir(make_santa):
    s = make_santa()
    s.save_transcript()                      # nothing logged -> nothing written
    assert not config.TRANSCRIPT_DIR.exists()
    s.reply("Emma", "hi")
    s.save_transcript()
    assert len(list(config.TRANSCRIPT_DIR.glob("*.txt"))) == 1
