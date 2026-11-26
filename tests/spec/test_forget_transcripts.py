"""Docs claims check S2/S4: chat.py saves a transcript of each typed session, so /forget must delete them too.

All paths are scratch folders. chat.py is driven with a fake Santa and a scripted input(): no model is contacted."""
import importlib
import sys
from pathlib import Path

from santa import config, memory

ROOT = Path(__file__).resolve().parents[2]


def test_remove_transcripts_deletes_only_txt_files_in_that_folder(tmp_path):
    d = tmp_path / "transcripts"
    d.mkdir()
    for name in ("20261101-100000.txt", "20261102-100000.txt", "keep.json", "notes.md"):
        (d / name).write_text("x")
    (d / "sub").mkdir()
    (d / "sub" / "inner.txt").write_text("x")
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    assert memory.remove_transcripts(d) == 2
    assert sorted(p.name for p in d.iterdir()) == ["keep.json", "notes.md", "sub"]
    assert (d / "sub" / "inner.txt").exists() and outside.exists()
    assert memory.remove_transcripts(d) == 0


def test_a_missing_folder_is_not_an_error(tmp_path):
    assert memory.remove_transcripts(tmp_path / "nope") == 0


def test_a_symlink_is_removed_but_never_its_target(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    target = tmp_path / "precious.txt"
    target.write_text("x")
    (d / "link.txt").symlink_to(target)
    assert memory.remove_transcripts(d) == 1
    assert target.exists()


class FakeSanta:
    """Just enough of santa.brain.Santa for chat.main()."""
    model = "fake"
    last_warmup_seconds = 0.0
    last_error = None

    def __init__(self):
        self.profiles = {"Emma": {"facts": ["has a cat"]}}
        self.history = []
        self.log = ["Emma: hi\nSanta: hello\n"]
        self.saved = []

    def warm_up(self):
        return True

    def end_call(self):
        return {}

    def save_transcript(self):
        self.saved.append(list(self.log))
        if self.log:
            config.TRANSCRIPT_DIR.mkdir(exist_ok=True)
            (config.TRANSCRIPT_DIR / "20261103-100000.txt").write_text("\n".join(self.log))


def _chat():
    sys.modules.pop("chat", None)
    sys.path.insert(0, str(ROOT))
    try:
        return importlib.import_module("chat")
    finally:
        sys.path.remove(str(ROOT))


def test_forget_in_chat_removes_saved_transcripts_and_the_sessions_own_text(monkeypatch, capsys):
    assert config.TRANSCRIPT_DIR.parent != ROOT / "local"          # scratch folder from tests/conftest.py
    config.TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("20261101-100000.txt", "20261102-100000.txt"):
        (config.TRANSCRIPT_DIR / name).write_text("old session")
    chat = _chat()
    fake = FakeSanta()
    monkeypatch.setattr(chat, "Santa", lambda: fake)
    lines = iter(["/forget", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    chat.main()
    out = capsys.readouterr().out
    assert "memory wiped; 2 transcript files removed" in out
    assert fake.profiles == {}
    assert fake.log == [] and fake.saved == [[]]                    # nothing from before /forget is saved at quit
    assert list(config.TRANSCRIPT_DIR.glob("*.txt")) == []
    sys.modules.pop("chat", None)


def test_forget_with_no_transcript_folder_still_works(monkeypatch, capsys):
    import shutil
    shutil.rmtree(config.TRANSCRIPT_DIR, ignore_errors=True)
    chat = _chat()
    fake = FakeSanta()
    monkeypatch.setattr(chat, "Santa", lambda: fake)
    lines = iter(["/forget", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    chat.main()
    assert "memory wiped; 0 transcript files removed" in capsys.readouterr().out
    sys.modules.pop("chat", None)


def test_forget_in_chat_also_removes_the_call_log(monkeypatch, capsys):
    from datetime import datetime
    from santa import calllog
    calllog.record("Emma", datetime(2026, 11, 20, 18, 0))
    config.CALLS_PATH.with_name("calls.json.corrupt").write_text("x")
    chat = _chat()
    monkeypatch.setattr(chat, "Santa", lambda: FakeSanta())
    lines = iter(["/forget", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    chat.main()
    assert list(config.CALLS_PATH.parent.glob("calls.json*")) == []
    sys.modules.pop("chat", None)
