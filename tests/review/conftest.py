"""Shared fixtures for the independent review tests.

No test here talks to a model server. The OpenAI client is replaced with a fake,
and profiles/transcripts go to temp paths.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# memory.load/save bind config.PROFILES_PATH as a default argument at import time,
# so point it at a throwaway file BEFORE anything imports santa.
_TMP = Path(tempfile.mkdtemp(prefix="santa-review-"))
os.environ["SANTA_PROFILES"] = str(_TMP / "profiles.json")

from santa import config, memory, safety  # noqa: E402
import santa.brain as brain  # noqa: E402

assert memory.load.__defaults__[0] == _TMP / "profiles.json", "would touch the real profiles.json"


# ----------------------------------------------------------------- fake client
def _chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class FakeClient:
    """Mimics client.chat.completions.create for streamed (Santa) and plain (extractor) calls.

    replies: list of str | Exception for streamed calls (popped in order; last one repeats).
    extract: str | Exception returned for non-streamed calls (fact extraction).
    """

    def __init__(self, replies=("Ho ho ho! Hello there!",), extract='{"facts": []}'):
        self.replies = list(replies)
        self.extract = extract
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if kw.get("stream"):
            r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
            if isinstance(r, Exception):
                raise r
            words = r.split(" ")
            return iter([_chunk(w + (" " if i < len(words) - 1 else "")) for i, w in enumerate(words)])
        if isinstance(self.extract, Exception):
            raise self.extract
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.extract))])

    @property
    def santa_calls(self):
        return [c for c in self.calls if c.get("stream")]

    @property
    def extract_calls(self):
        return [c for c in self.calls if not c.get("stream")]


@pytest.fixture
def tmp_profiles(tmp_path, monkeypatch):
    """Redirect memory load/save to a temp file for the duration of a test."""
    p = tmp_path / "profiles.json"
    real_load, real_save = memory.load, memory.save
    monkeypatch.setattr(memory, "load", lambda path=p: real_load(path))
    monkeypatch.setattr(memory, "save", lambda profiles, path=p: real_save(profiles, path))
    monkeypatch.setattr(config, "TRANSCRIPT_DIR", tmp_path / "transcripts")
    return p


@pytest.fixture
def make_santa(tmp_profiles):
    """Build a Santa with a fake client and the three test children."""

    def _make(replies=("Ho ho ho! Hello there!",), extract='{"facts": []}', profiles=None):
        s = brain.Santa(model="fake-model", base_url="http://127.0.0.1:9/never-used")
        s.client = FakeClient(replies, extract)
        s.profiles = profiles if profiles is not None else {
            "Emma": {"age": 4, "facts": []},
            "Leo": {"age": 3, "facts": []},
            "Ziv": {"age": 4, "facts": []},
        }
        return s

    return _make
