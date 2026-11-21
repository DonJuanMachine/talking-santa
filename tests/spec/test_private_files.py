"""The children's data is private to the owner's macOS account (VulnHunter run 2: VULN-009, VULN-014, VULN-015).

Profiles, their .bak and .corrupt copies, chat transcripts and --debug-audio recordings are created 0600 (folders
0700) whatever the process umask, and both entry points set umask 077 so anything else they write is private too.
Before, a start that did not go through start-santa.sh (python -m santa.web, run-web.sh, chat.py) left them 0644 and
0755, so another account on the Mac could read the children's names and facts.
"""
import importlib
import os
import stat
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from santa import config, memory
from santa.brain import Santa
from santa.web.audio import write_debug_wav

from _startup import launch

ROOT = Path(__file__).resolve().parents[2]


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


@pytest.fixture
def open_umask():
    """The permissive umask a plain shell has, so a passing test means the code sets the mode, not the umask."""
    old = os.umask(0o022)
    yield
    os.umask(old)


def test_saved_profiles_and_their_backup_are_owner_only(tmp_path, open_umask):
    path = tmp_path / "profiles.json"
    memory.save({"A": {"facts": []}}, path)
    memory.save({"A": {"facts": ["likes trains"]}}, path)      # the second save makes the .bak
    assert mode(path) == 0o600
    assert mode(memory._bak(path)) == 0o600


def test_an_old_readable_profiles_file_becomes_owner_only_on_the_next_save(tmp_path, open_umask):
    path = tmp_path / "profiles.json"
    path.write_text('{"children": {}}\n')
    path.chmod(0o644)
    memory.save({}, path)
    assert mode(path) == 0o600


def test_the_corrupt_copy_kept_for_the_adult_is_owner_only(tmp_path, open_umask, capsys):
    path = tmp_path / "profiles.json"
    path.write_text("{ not json")
    memory.load(path)
    assert mode(path.with_name(path.name + ".corrupt")) == 0o600


def test_chat_transcripts_and_their_folder_are_owner_only(monkeypatch, tmp_path, open_umask):
    folder = tmp_path / "transcripts"
    monkeypatch.setattr(config, "TRANSCRIPT_DIR", folder)
    Santa.save_transcript(types.SimpleNamespace(log=["child A: hi santa", "Santa: Ho ho ho!"]))
    (saved,) = folder.glob("*.txt")
    assert mode(folder) == 0o700
    assert mode(saved) == 0o600


def test_debug_recordings_and_their_folder_are_owner_only(tmp_path, open_umask):
    wav = tmp_path / "debug_audio" / "utt.wav"
    write_debug_wav(wav, np.zeros(160, dtype=np.float32))
    assert mode(wav.parent) == 0o700
    assert mode(wav) == 0o600


def current_umask() -> int:
    old = os.umask(0o022)
    os.umask(old)
    return old


def test_the_voice_app_entry_point_sets_a_private_umask(monkeypatch, open_umask):
    launch(monkeypatch, [])                       # main() up to uvicorn.run, which is recorded, not run
    assert current_umask() == 0o077


def test_the_typed_chat_entry_point_sets_a_private_umask(monkeypatch, open_umask):
    monkeypatch.syspath_prepend(str(ROOT))
    sys.modules.pop("chat", None)
    chat = importlib.import_module("chat")
    seen = []

    class Stop(Exception):
        pass

    def fake_santa():
        seen.append(os.umask(0o077))
        raise Stop
    monkeypatch.setattr(chat, "Santa", fake_santa)
    with pytest.raises(Stop):
        chat.main()
    assert seen == [0o077]
