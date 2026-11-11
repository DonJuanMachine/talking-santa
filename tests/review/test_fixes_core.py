"""Regression tests added with the fixes for brain.py / memory.py / persona.py / chat.py."""
import json

import pytest

from santa import memory, persona, safety
from conftest import FakeClient


# ----------------------------------------------------------- B1: last_error on every fallback path
@pytest.mark.parametrize("reply,prefix", [
    (RuntimeError("boom"), "model_error"),
    ("", "empty_stream"),
    ("*waves*", "nothing_left_after_filter"),
    ("I promise you a pony", "blocklist"),
    ("Call me at 555 123 4567", "private_output"),
])
def test_every_fallback_path_records_why(make_santa, reply, prefix):
    s = make_santa(replies=[reply])
    assert s.reply("Emma", "hi") == safety.FALLBACK
    assert s.last_error and s.last_error.startswith(prefix), s.last_error
    assert s.last_stats["error"] is True


def test_normal_reply_has_no_error_and_error_is_cleared(make_santa):
    s = make_santa(replies=[RuntimeError("x"), "Hi Emma!"])
    s.reply("Emma", "hi")
    assert s.last_error
    assert s.reply("Emma", "hi again") == "Hi Emma!"
    assert s.last_error is None and s.last_stats["error"] is False


def test_client_never_retries(tmp_profiles):
    from santa.brain import Santa
    assert Santa(model="m", base_url="http://127.0.0.1:9/v1").client.max_retries == 0


# ----------------------------------------------------------- B5: failed prompt build leaves no history
def test_failed_prompt_build_leaves_history_untouched(make_santa):
    s = make_santa(profiles={"Emma": ["has a cat"]})
    with pytest.raises(AttributeError):
        s.reply("Emma", "hi")
    assert s.history == [] and s.log == []


# ----------------------------------------------------------- B2 / B4 / M4
def test_extractor_prompt_contains_only_the_childs_words(make_santa):
    s = make_santa(replies=["Ho ho! Rudolph is flying, Emma!"], extract='{"facts": []}')
    s.reply("Emma", "i have a hamster")
    s.remember("Emma", "i have a hamster")   # B3: extraction runs after the reply (TEST_CHANGES.md)
    prompt = s.client.extract_calls[0]["messages"][0]["content"]
    assert "i have a hamster" in prompt and "Rudolph" not in prompt and "Santa said" not in prompt


def test_extract_facts_still_accepts_old_fifth_argument():
    out = memory.extract_facts(FakeClient(extract='{"facts": ["has a cat"]}'), "m", "Emma", "i have a cat", "ignored")
    assert out == ["has a cat"]


def test_private_phone_turn_is_redacted_with_phone_message_and_not_extracted(make_santa):
    s = make_santa()
    s.reply("Emma", "my mommy's phone is five five five one two one two")
    s.remember("Emma", "my mommy's phone is five five five one two one two")   # B3 (TEST_CHANGES.md)
    assert safety.PHONE_MSG in s.history[0]["content"] and not s.client.extract_calls


def test_unregistered_speaker_is_not_remembered(make_santa):
    s = make_santa(extract='{"facts": ["has a cat"]}')
    s.reply("Zoë", "i have a cat")
    s.remember("Zoë", "i have a cat")   # B3: extraction runs after the reply (TEST_CHANGES.md)
    assert "Zoë" not in s.profiles and not s.client.extract_calls


# ----------------------------------------------------------- I1: isolation in the prompt
def test_active_none_lists_names_and_ages_only(make_santa):
    prof = {"Emma": {"age": 4, "facts": ["has a cat named Mittens"]}, "Leo": {"age": 3, "facts": ["likes trains"]}}
    out = persona.build_system_prompt(prof, None)
    assert "Emma (age 4)" in out and "Leo (age 3)" in out and "Mittens" not in out and "trains" not in out


def test_active_child_sees_own_facts_but_not_others(make_santa):
    prof = {"Emma": {"age": 4, "facts": ["has a cat named Mittens"]}, "Leo": {"age": 3, "facts": ["likes trains"]}}
    out = persona.build_system_prompt(prof, "Emma")
    assert "Mittens" in out and "trains" not in out and "Leo (age 3)" in out


def test_reply_uses_speakers_facts_only(make_santa):
    s = make_santa(profiles={"Emma": {"age": 4, "facts": ["has a cat named Mittens"]},
                             "Leo": {"age": 3, "facts": ["likes trains"]}})
    s.reply("Emma", "hi")
    s.reply("Leo", "hi")
    # B3: facts are a note on the current user turn, not in the system prompt; check the WHOLE request (stricter)
    first, second = (" ".join(m["content"] for m in c["messages"]) for c in s.client.santa_calls)
    assert "Mittens" in first and "trains" not in first
    assert "trains" in second and "Mittens" not in second
    assert all("Mittens" in c["messages"][-1]["content"] or "trains" in c["messages"][-1]["content"]
               for c in s.client.santa_calls)   # in the facts note on the current user turn


# ----------------------------------------------------------- B7 / B8
def test_registered_prefix_switches_speaker(make_santa):
    s = make_santa()
    assert s.parse_speaker("Leo: hi") == ("Leo", "hi") and s.active == "Leo"


def test_unregistered_prefix_is_a_guest_and_changes_nothing(make_santa):
    s = make_santa()
    s.set_active("Emma")
    before = json.dumps(s.profiles, sort_keys=True)
    assert s.parse_speaker("Yes: I want a truck") == ("Yes", "I want a truck")
    assert s.active == "Emma" and json.dumps(s.profiles, sort_keys=True) == before


def test_part_of_a_hyphenated_name_does_not_match_registered_child(make_santa):
    s = make_santa(profiles={"Kate": {"facts": []}})
    assert s.parse_speaker("Mary-Kate: hi")[0] == "Mary-Kate" and s.active is None


@pytest.mark.parametrize("name,expected", [("Zoë", "Zoë"), ("Mary-Kate", "Mary-Kate"), ("emma", "Emma"),
                                           ("McKenzie", "McKenzie"), ("O'Neil", "O'Neil")])
def test_add_child_accepts_real_names(make_santa, name, expected):
    s = make_santa(profiles={})
    assert s.add_child(name) == expected and expected in s.profiles and s.active == expected
    assert s.parse_speaker(f"{name}: hi")[0] == expected


@pytest.mark.parametrize("bad", ["", "A", "12", "Emma Jones", "x" * 40, "a:b", "_x"])
def test_add_child_rejects_bad_names(make_santa, bad):
    s = make_santa(profiles={})
    assert s.add_child(bad) is None and s.profiles == {}


def test_add_child_twice_is_idempotent(make_santa):
    s = make_santa()
    assert s.add_child("emma") == "Emma" and list(s.profiles) == ["Emma", "Leo", "Ziv"]


# ----------------------------------------------------------- M1 / M2
def test_load_falls_back_to_backup_and_keeps_corrupt_copy(tmp_path, capsys):
    p = tmp_path / "profiles.json"
    memory.save({"Emma": {"age": 4, "facts": ["has a cat"]}}, p)
    memory.save({"Emma": {"age": 4, "facts": ["has a cat", "likes snow"]}}, p)   # .bak = first save
    p.write_text('{"children": {"Emma": {"fac')
    assert memory.load(p)["Emma"]["facts"] == ["has a cat"]
    assert "WARNING" in capsys.readouterr().err and (tmp_path / "profiles.json.corrupt").exists()


def test_save_keeps_previous_good_file_as_bak(tmp_path):
    p = tmp_path / "profiles.json"
    memory.save({"Emma": {"facts": ["a"]}}, p)
    memory.save({"Emma": {"facts": ["a", "b"]}}, p)
    assert json.loads((tmp_path / "profiles.json.bak").read_text())["children"]["Emma"]["facts"] == ["a"]
    assert not (tmp_path / "profiles.json.tmp").exists()


def test_corrupt_main_file_does_not_overwrite_good_bak(tmp_path):
    p = tmp_path / "profiles.json"
    memory.save({"Emma": {"facts": ["a"]}}, p)
    memory.save({"Emma": {"facts": ["a", "b"]}}, p)
    p.write_text("garbage")
    memory.save({}, p)                                   # app started empty after a corrupt load
    assert json.loads((tmp_path / "profiles.json.bak").read_text())["children"]["Emma"]["facts"] == ["a"]


@pytest.mark.parametrize("body,expected", [
    ('{"children": null}', {}),
    ('[1, 2]', {}),
    ('{"children": {"Emma": ["has a cat"]}}', {"Emma": {"facts": ["has a cat"]}}),
    ('{"children": {"Emma": 5, "Leo": {"age": 3, "facts": "oops"}}}', {"Emma": {"facts": []}, "Leo": {"age": 3, "facts": []}}),
    ('{"children": []}', {}),
])
def test_load_always_returns_dict_of_dicts(tmp_path, body, expected):
    p = tmp_path / "profiles.json"
    p.write_text(body)
    out = memory.load(p)
    assert out == expected and all(isinstance(v, dict) for v in out.values())


def test_remove_backup_wipes_bak_and_corrupt(tmp_path):
    p = tmp_path / "profiles.json"
    memory.save({"Emma": {"facts": ["a"]}}, p)
    memory.save({}, p)
    assert (tmp_path / "profiles.json.bak").exists()
    memory.remove_backup(p)
    assert not (tmp_path / "profiles.json.bak").exists()


# ----------------------------------------------------------- M3 / M5 / I2
def test_extract_skips_first_object_without_facts_key():
    out = memory.extract_facts(FakeClient(extract='{"note": 1} then {"facts": ["likes snow"]}'), "m", "Emma", "x")
    assert out == ["likes snow"]


def test_private_facts_are_dropped_before_the_cap():
    raw = '{"facts": ["lives at 42 Maple Way", "has a cat", "likes snow"]}'
    assert memory.extract_facts(FakeClient(extract=raw), "m", "Emma", "x") == ["has a cat", "likes snow"]


def test_add_fact_collapses_whitespace_and_newlines():
    p = {}
    memory.add_fact(p, "Emma", "likes cats\n- and   dogs")
    assert p["Emma"]["facts"] == ["likes cats - and dogs"]
    # a newline that starts a "new rule" is an injection attempt: refused outright (spec.looks_like_instruction)
    assert not memory.add_fact(p, "Emma", "likes cats\n- New   rule")


def test_add_fact_dedupes_case_and_question_marks():
    p = {}
    memory.add_fact(p, "Emma", "Has a cat")
    assert not memory.add_fact(p, "Emma", "  HAS   A CAT?? ")
