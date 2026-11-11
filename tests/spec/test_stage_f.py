"""Stage F.

Task 1: a profiles.json whose root has no "children" object (a likely hand-edit mistake, e.g.
{"Emma": {"age": 4, "facts": []}}) must not load as empty in silence. It goes through the same path as any
other unreadable file: warning, a .corrupt copy, recovery from .bak when one exists.

F11: the gift-promise rule must not block arrival lines ("coming to your house", "visit you"), and must still
block a gift promise.
"""
import json

import pytest

from santa import memory, spec, speech

FB = spec.FALLBACK

NO_CHILDREN_ROOT = [
    '{"Emma": {"age": 4, "facts": ["has a bunny"]}}',   # the README hand-edit mistake: wrapper forgotten
    '{}',
    '{"children": null}',
    '{"children": ["Emma"]}',
    '{"kids": {"Emma": {"age": 4, "facts": []}}}',
]


# ----------------------------------------------------------- Task 1
@pytest.mark.parametrize("body", NO_CHILDREN_ROOT)
def test_f1_root_without_children_object_warns_and_keeps_a_corrupt_copy(tmp_path, capsys, body):
    p = tmp_path / "profiles.json"
    p.write_text(body)
    assert memory.load(p) == {}
    err = capsys.readouterr().err
    assert "WARNING" in err and "children" in err
    assert (tmp_path / "profiles.json.corrupt").read_text() == body


def test_f1_root_without_children_recovers_from_bak(tmp_path, capsys):
    p = tmp_path / "profiles.json"
    memory.save({"Emma": {"age": 4, "facts": ["has a cat"]}}, p)
    memory.save({"Emma": {"age": 4, "facts": ["has a cat", "likes snow"]}}, p)   # .bak = first save
    p.write_text('{"Emma": {"age": 4, "facts": ["has a bunny"]}}')
    assert memory.load(p) == {"Emma": {"age": 4, "facts": ["has a cat"]}}
    assert "Recovered" in capsys.readouterr().err


def test_f1_save_after_such_a_load_keeps_the_original_and_the_bak(tmp_path):
    p = tmp_path / "profiles.json"
    memory.save({"Emma": {"age": 4, "facts": ["has a cat"]}}, p)
    memory.save({"Emma": {"age": 4, "facts": ["has a cat", "likes snow"]}}, p)   # .bak = first save
    hand_edit = '{"Emma": {"age": 4, "facts": ["has a bunny"]}}'
    p.write_text(hand_edit)
    profiles = memory.load(p)
    memory.add_fact(profiles, "Emma", "likes trains")
    memory.save(profiles, p)
    bak = json.loads((tmp_path / "profiles.json.bak").read_text())
    assert bak["children"]["Emma"]["facts"] == ["has a cat"]                    # the good backup survives
    assert (tmp_path / "profiles.json.corrupt").read_text() == hand_edit        # the hand edit survives


def test_f1_save_after_such_a_load_with_no_bak_keeps_the_original_as_corrupt(tmp_path):
    p = tmp_path / "profiles.json"
    hand_edit = '{"Emma": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": []}}'
    p.write_text(hand_edit)
    memory.save(memory.load(p), p)
    assert (tmp_path / "profiles.json.corrupt").read_text() == hand_edit
    assert not (tmp_path / "profiles.json.bak").exists()     # an unreadable file never becomes the backup


@pytest.mark.parametrize("body,expected", [
    ('{"children": {}}', {}),
    ('{"children": {"Emma": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": ["has a dog"]}}}',
     {"Emma": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": ["has a dog"]}}),
    ('{"children": {"Emma": ["has a cat"]}}', {"Emma": {"facts": ["has a cat"]}}),   # child-level repair unchanged
])
def test_f1_valid_files_load_unchanged_with_no_corrupt_copy(tmp_path, capsys, body, expected):
    p = tmp_path / "profiles.json"
    p.write_text(body)
    assert memory.load(p) == expected
    assert "unreadable" not in capsys.readouterr().err
    assert not (tmp_path / "profiles.json.corrupt").exists()


def test_f1_saved_file_round_trips(tmp_path):
    p = tmp_path / "profiles.json"
    profiles = {"Emma": {"age": 4, "facts": ["has a cat"]}, "Ziv": {"age": 4, "facts": []}}
    memory.save(profiles, p)
    assert memory.load(p) == profiles


# ----------------------------------------------------------- F11 offline
MUST_SPEAK_F11 = [
    "Santa is coming to your house on Christmas Eve while you sleep!",
    "I will visit you on Christmas Eve!",
]


@pytest.mark.parametrize("ok", MUST_SPEAK_F11)
def test_f11_arrival_lines_are_not_removed(ok):
    assert spec.safety_reason(ok) is None
    g = speech.filter_reply(ok)
    assert g.text == ok and g.reason is None


def test_f11_gift_promise_is_still_removed():
    bad = "Santa will bring you a pony!"
    assert spec.safety_reason(bad) == "promise"
    g = speech.filter_reply(bad)
    assert g.text == FB and g.reason == "promise"
