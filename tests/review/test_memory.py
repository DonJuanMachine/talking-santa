"""Review tests for santa/memory.py."""
import json
from pathlib import Path

import pytest

from santa import memory
from conftest import FakeClient


def _facts_from(raw):
    return memory.extract_facts(FakeClient(extract=raw), "fake", "Emma", "hi", "Ho ho!")


# ----------------------------------------------------------- load / save
def test_load_truncated_file(tmp_path):
    p = tmp_path / "profiles.json"
    p.write_text('{"children": {"Emma": {"age": 4, "facts": ["has a c')
    assert isinstance(memory.load(p), dict)


def test_load_null_children(tmp_path):
    p = tmp_path / "profiles.json"
    p.write_text('{"children": null}')
    assert isinstance(memory.load(p), dict)


def test_save_interrupted_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "profiles.json"
    memory.save({"Emma": {"age": 4, "facts": ["has a cat"]}}, p)
    real_write = Path.write_text

    def crash_halfway(self, data, *a, **k):
        real_write(self, data[: len(data) // 2], *a, **k)
        raise OSError("power cut")

    monkeypatch.setattr(Path, "write_text", crash_halfway)
    with pytest.raises(OSError):
        memory.save({"Emma": {"age": 4, "facts": ["has a cat", "likes snow"]}}, p)
    monkeypatch.setattr(Path, "write_text", real_write)
    assert memory.load(p)["Emma"]["facts"][0] == "has a cat"


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "profiles.json"
    data = {"Emma": {"age": 4, "facts": ["likes {braces}", "snow ❄"]}}
    memory.save(data, p)
    assert memory.load(p) == data


# ----------------------------------------------------------- extract_facts
def test_extract_plain_and_fenced_json():
    assert _facts_from('{"facts": ["has a cat named Mittens"]}') == ["has a cat named Mittens"]
    assert _facts_from('```json\n{"facts": ["likes snow"]}\n```') == ["likes snow"]
    assert _facts_from('{"facts": ["likes {blue} cars"]}') == ["likes {blue} cars"]
    assert _facts_from('{"facts": ["a", "b", "c"]}') == ["a", "b"]       # capped at 2
    assert _facts_from("no json here") == []
    assert _facts_from('{"facts": [1, null, "ok"]}') == ["ok"]


def test_extract_with_trailing_json_object():
    raw = 'Sure! {"facts": ["has a dog named Rex"]}\nExample format: {"facts": []}'
    assert _facts_from(raw) == ["has a dog named Rex"]


def test_extract_facts_string_not_split_into_chars():
    assert _facts_from('{"facts": "has a cat"}') in ([], ["has a cat"])   # current: ['h', 'a']


def test_extract_errors_fail_soft():
    assert memory.extract_facts(FakeClient(extract=RuntimeError("down")), "m", "Emma", "hi", "ho") == []
    assert _facts_from("[1, 2]") == []
    assert _facts_from('{"facts": ') == []


@pytest.mark.parametrize("fact", ["lives at 42 Maple Way", "mommy's phone is 555 123 4567", "last name is Johnson"])
def test_private_fact_rejected(fact):
    profiles = {}
    stored = [f for f in _facts_from(json.dumps({"facts": [fact]})) if memory.add_fact(profiles, "Emma", f)]
    assert not stored


# ----------------------------------------------------------- add_fact
def test_add_fact_case_dedupe_cap_and_trim():
    p = {}
    assert memory.add_fact(p, "Emma", "Has a cat.")
    assert not memory.add_fact(p, "Emma", "has a cat")
    assert not memory.add_fact(p, "Emma", "   ")
    assert not memory.add_fact(p, "Emma", "x" * 101)
    assert memory.add_fact(p, "Emma", "x" * 100)
    for i in range(30):
        memory.add_fact(p, "Emma", f"fact {i}")
    assert len(p["Emma"]["facts"]) == 20 and p["Emma"]["facts"][-1] == "fact 29"


@pytest.mark.parametrize("dup", ["has  a cat", "has a cat!"])
def test_add_fact_dedupes_whitespace_and_punctuation(dup):
    p = {}
    memory.add_fact(p, "Emma", "has a cat")
    assert not memory.add_fact(p, "Emma", dup)


# ----------------------------------------------------------- match_name
def test_match_name():
    prof = {"Emma": {}, "Leo": {}, "Ziv": {}}
    assert memory.match_name(prof, "emma") == "Emma"
    assert memory.match_name(prof, "Emmanuel") is None
    assert memory.match_name(prof, "Leon") is None
    assert memory.match_name({"A.J": {}}, "AXJ") is None    # name is regex-escaped


# ----------------------------------------------------------- nicknames and family names
def test_nicknames_resolve_to_the_child_and_ambiguous_ones_are_dropped():
    prof = {"Jonny": {"nicknames": ["Jonathan", "Tiger"]}, "Ziv": {"nicknames": ["Tiger", "Jonny"]}}
    assert memory.aliases(prof) == {"jonathan": "Jonny"}          # "Tiger" is shared, "Jonny" is a real name
    assert memory.match_name(prof, "hi I'm Jonathan") == "Jonny"


def test_repair_cleans_nicknames_and_family(tmp_path):
    p = tmp_path / "p.json"
    p.write_text('{"children": {"Lumi": {"nicknames": "Noni", "family": {"grandmother": "Gammy", "x": 5}}}}')
    lumi = memory.load(p)["Lumi"]
    assert lumi["nicknames"] == ["Noni"] and lumi["family"] == {"grandmother": ["Gammy"]}


def test_facts_note_lists_nicknames_and_family_for_that_child_only():
    from santa import persona
    note = persona.facts_note("Lumi", ["likes art"], {"nicknames": ["Noni"], "family": {"grandmother": ["Gammy"]}})
    assert "also called Noni" in note and "grandmother: Gammy" in note and "likes art" in note
    assert persona.facts_note("Lumi", ["likes art"]) == persona.facts_note("Lumi", ["likes art"], {})


def test_heard_name_accepts_nicknames():
    from santa.web.session import heard_name
    assert heard_name("hi santa it's jonathan", ["Jonny", "Ziv"], {"jonathan": "Jonny"}) == "Jonny"
    assert heard_name("jonny and jonathan", ["Jonny"], {"jonathan": "Jonny"}) is None   # said twice


# ----------------------------------------------------------- near-duplicate facts
def test_near_duplicate_facts_are_not_added():
    prof = {"Lumi": {"facts": ["likes Barbie Dreamhouse", "likes cats"]}}
    assert not memory.add_fact(prof, "Lumi", "Likes Barbie Dream House")
    assert not memory.add_fact(prof, "Lumi", "likes barbie dreamhouse!")
    assert memory.add_fact(prof, "Lumi", "likes cars")            # short facts differ by one letter: still new
    assert memory.add_fact(prof, "Lumi", "wants a drawing pad")
    assert len(prof["Lumi"]["facts"]) == 4


def test_near_duplicates_are_dropped_on_load(tmp_path):
    p = tmp_path / "p.json"
    p.write_text('{"children": {"Lumi": {"facts": ["likes Barbie Dreamhouse", "likes Barbie Dream House", "wants a pad"]}}}')
    assert memory.load(p)["Lumi"]["facts"] == ["likes Barbie Dreamhouse", "wants a pad"]
