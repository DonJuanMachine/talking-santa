"""Call log (santa/calllog.py): the call page keeps when each registered child called (names, dates and times only) in
local/calls.json, and tells Santa on that child's turn that they talked before. chat.py never writes it.

tests/conftest.py gives every test its own empty calls.json path. No model is contacted (FakeClient)."""
import _support  # noqa: F401  (temp profiles; must come first)

import copy
import json
import os
import stat
from datetime import datetime, timedelta

import pytest

from _support import FakeClient
from santa import calllog, config, persona
from santa.brain import Santa

KIDS = {"Emma": {"age": 4, "facts": ["has a cat"]}, "Leo": {"age": 3, "facts": []}}
NOW = datetime(2026, 11, 25, 18, 30)          # a Wednesday evening


def santa(call_log=True, now=NOW):
    s = Santa(client=FakeClient(replies=("Ho ho, hello there, my friend!",)), profiles=copy.deepcopy(KIDS),
              call_log=call_log)
    s.clock = lambda: now
    return s


def say(s, speaker, text="hi Santa"):
    for _ in s.reply_stream(speaker, text):
        pass


def last_user_turn(s):
    return s.client.calls[-1]["messages"][-1]["content"]


def stored():
    return json.loads(config.CALLS_PATH.read_text())["calls"]


# -- what gets logged ---------------------------------------------------------------------------------------------
def test_a_child_is_logged_once_on_their_second_turn_with_the_time_of_their_first():
    s = santa()
    say(s, "Emma")
    assert not config.CALLS_PATH.exists()                       # one turn is not a call yet
    s.clock = lambda: NOW + timedelta(minutes=3)
    say(s, "Emma")
    assert stored() == {"Emma": ["2026-11-25T18:30"]}
    say(s, "Emma")
    say(s, "Emma")
    assert stored() == {"Emma": ["2026-11-25T18:30"]}           # once per call


def test_each_child_is_counted_on_their_own_turns():
    s = santa()
    say(s, "Emma")
    say(s, "Leo")
    assert not config.CALLS_PATH.exists()
    say(s, "Leo")
    assert stored() == {"Leo": ["2026-11-25T18:30"]}
    say(s, "Emma")
    assert set(stored()) == {"Emma", "Leo"}


def test_turns_santa_never_answered_do_not_count():
    s = Santa(client=FakeClient(replies=(RuntimeError("runner down"), RuntimeError("runner down"),
                                         "Hello there, my friend!")), profiles=copy.deepcopy(KIDS), call_log=True)
    s.clock = lambda: NOW
    say(s, "Emma")
    say(s, "Emma")
    assert s.last_reply.fallback and not config.CALLS_PATH.exists()   # two fallbacks: no call happened
    s.clock = lambda: NOW + timedelta(minutes=2)
    say(s, "Emma")
    assert not config.CALLS_PATH.exists()                        # one answered turn is not a call yet
    say(s, "Emma")
    assert stored() == {"Emma": ["2026-11-25T18:32"]}            # the time of the first answered turn


def test_guests_and_unregistered_names_are_never_logged():
    s = santa()
    for speaker in (None, None, "Zed", "Zed"):
        say(s, speaker)
    assert not config.CALLS_PATH.exists()


def test_chat_py_style_santa_never_logs_or_reads_the_log():
    calllog.record("Emma", NOW - timedelta(days=1))
    before = config.CALLS_PATH.read_text()
    s = santa(call_log=False)
    say(s, "Emma")
    say(s, "Emma")
    assert config.CALLS_PATH.read_text() == before
    assert "call log" not in last_user_turn(s)


def test_santa_call_log_0_turns_it_off(monkeypatch):
    calllog.record("Emma", NOW - timedelta(days=1))
    before = config.CALLS_PATH.read_text()
    monkeypatch.setenv("SANTA_CALL_LOG", "0")
    s = santa()
    say(s, "Emma")
    say(s, "Emma")
    assert config.CALLS_PATH.read_text() == before
    assert "call log" not in last_user_turn(s)


def test_the_call_page_brain_logs_calls():
    from santa.web.brain_adapter import SantaBrain
    b = SantaBrain(client=FakeClient(replies=("Hello there, my friend!",)), profiles=copy.deepcopy(KIDS))
    b.new_call()
    assert b.santa.call_log_on
    for _ in range(2):
        b.reply("Emma", "hi Santa", lambda sentence: None)
    assert list(stored()) == ["Emma"]


# -- what Santa is told -------------------------------------------------------------------------------------------
def test_the_note_is_on_the_active_childs_turn_only_and_never_in_history():
    calllog.record("Emma", NOW - timedelta(days=3))
    calllog.record("Emma", NOW - timedelta(days=1, hours=1))
    s = santa()
    say(s, "Emma")
    turn = last_user_turn(s)
    assert "talked with Emma on the phone before, twice" in turn and "yesterday evening" in turn
    say(s, "Leo")
    assert "call log" not in last_user_turn(s)                   # Leo never called; Emma's calls are not shown
    assert not any("call log" in h["content"] for h in s.history)


def test_this_calls_own_entry_is_not_in_its_notes():
    s = santa()
    say(s, "Emma")
    say(s, "Emma")                                               # logged now
    say(s, "Emma")
    assert "call log" not in last_user_turn(s)
    s2 = santa(now=NOW + timedelta(days=1))                      # the next call sees it
    say(s2, "Emma")
    assert "before, once. The last time was yesterday evening." in last_user_turn(s2)


def test_no_note_without_earlier_calls():
    s = santa()
    say(s, "Emma")
    assert "call log" not in last_user_turn(s)


@pytest.mark.parametrize("last, now, want", [
    (datetime(2026, 11, 25, 18, 0), NOW, "earlier today"),
    (datetime(2026, 11, 25, 9, 0), NOW, "earlier today, in the morning"),
    (datetime(2026, 11, 25, 2, 0), datetime(2026, 11, 25, 9, 0), "last night"),
    (datetime(2026, 11, 24, 15, 0), NOW, "yesterday afternoon"),
    (datetime(2026, 11, 24, 22, 0), NOW, "last night"),
    (datetime(2026, 11, 22, 18, 0), NOW, "3 days ago, on Sunday evening"),
    (datetime(2026, 11, 15, 18, 0), NOW, "10 days ago"),
    (datetime(2026, 10, 25, 18, 0), NOW, "about 4 weeks ago"),
    (datetime(2026, 6, 1, 18, 0), NOW, "about 5 months ago"),
    (datetime(2025, 11, 1, 18, 0), NOW, "more than a year ago"),
    (datetime(2026, 11, 26, 18, 0), NOW, "recently"),            # the clock went back
    # After midnight is still the night before: a call 22 hours ago is not "earlier today", and 1:30 AM on Tuesday
    # was Monday night, not last night.
    (datetime(2026, 11, 25, 1, 0), datetime(2026, 11, 25, 23, 0), "last night"),
    (datetime(2026, 11, 24, 1, 30), datetime(2026, 11, 25, 19, 0), "2 days ago, on Monday night"),
    (datetime(2026, 11, 24, 22, 0), datetime(2026, 11, 25, 1, 0), "earlier tonight"),
    (datetime(2026, 11, 24, 18, 0), datetime(2026, 11, 25, 1, 0), "earlier today, in the evening"),
])
def test_relative_times(last, now, want):
    assert persona._when(last, now) == want


def test_counts_in_words():
    day = datetime(2026, 11, 1, 10, 0)
    assert "before, once." in persona.calls_note("Emma", [day], NOW)
    assert "before, 3 times." in persona.calls_note("Emma", [day] * 3, NOW)
    assert "before, more than 49 times." in persona.calls_note("Emma", [day] * 50, NOW)
    assert persona.calls_note("Emma", [], NOW) == ""


# -- the file -----------------------------------------------------------------------------------------------------
def test_keeps_the_newest_50_per_child_oldest_first():
    start = datetime(2026, 1, 1, 9, 0)
    for i in range(55):
        calllog.record("Emma", start + timedelta(days=i))
    calllog.record("Leo", start)
    times = stored()["Emma"]
    assert len(times) == 50 and times == sorted(times)
    assert times[0] == "2026-01-06T09:00" and times[-1] == "2026-02-24T09:00"
    assert stored()["Leo"] == ["2026-01-01T09:00"]


def test_the_file_holds_names_and_times_only_and_is_private():
    calllog.record("Emma", NOW)
    assert config.CALLS_PATH.read_text() == '{\n  "calls": {\n    "Emma": [\n      "2026-11-25T18:30"\n    ]\n  }\n}\n'
    assert stat.S_IMODE(os.stat(config.CALLS_PATH).st_mode) == 0o600


def test_a_broken_file_is_kept_as_corrupt_and_a_new_log_starts(capsys):
    config.CALLS_PATH.write_text("{not json")
    assert calllog.load() == {}
    assert calllog.record("Emma", NOW)
    assert stored() == {"Emma": ["2026-11-25T18:30"]}
    corrupt = config.CALLS_PATH.with_name("calls.json.corrupt")
    assert corrupt.read_text() == "{not json"
    assert "unreadable" in capsys.readouterr().err


def _corrupt_files():
    return sorted(p.name for p in config.CALLS_PATH.parent.glob("calls.json.corrupt*"))


def test_a_second_broken_file_never_overwrites_the_first_copy(capsys):
    config.CALLS_PATH.write_text("{first broken")
    calllog.load()
    calllog.record("Emma", NOW)                                  # reads the same broken file again: no second copy
    assert _corrupt_files() == ["calls.json.corrupt"]
    config.CALLS_PATH.write_text("{second broken")
    calllog.load()
    calllog.load()
    assert _corrupt_files() == ["calls.json.corrupt", "calls.json.corrupt.2"]
    assert config.CALLS_PATH.with_name("calls.json.corrupt").read_text() == "{first broken"
    assert config.CALLS_PATH.with_name("calls.json.corrupt.2").read_text() == "{second broken"
    assert "kept as calls.json.corrupt.2" in capsys.readouterr().err


def test_bad_hand_edited_entries_are_skipped():
    config.CALLS_PATH.write_text(json.dumps({"calls": {"Emma": ["yesterday", 5, "2026-11-20T10:00"], "Leo": "x"}}))
    assert calllog.load() == {"Emma": [datetime(2026, 11, 20, 10, 0)]}


def test_a_failed_save_does_not_stop_the_call(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(calllog, "_write", boom)
    s = santa()
    say(s, "Emma")
    say(s, "Emma")
    assert s.last_error is None
    assert "could not save the call log" in capsys.readouterr().err


def test_remove_deletes_the_log_and_its_copies():
    calllog.record("Emma", NOW)
    for suffix in (".tmp", ".corrupt", ".corrupt.2", ".corrupt.3"):
        config.CALLS_PATH.with_name("calls.json" + suffix).write_text("x")
    calllog.remove()
    assert list(config.CALLS_PATH.parent.glob("calls.json*")) == []
    calllog.remove()                                             # nothing there: not an error
