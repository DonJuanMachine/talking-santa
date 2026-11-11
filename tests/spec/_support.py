"""Setup shared by tests/spec (imported first by test_spec.py; deliberately not a conftest.py, so the old suite's
`from conftest import ...` keeps resolving to tests/review/conftest.py).

- profiles go to a temp file (never the real profiles.json); hypothesis keeps its cache in a temp dir.
- FakeClient: no model server is ever contacted.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
_TMP = Path(tempfile.mkdtemp(prefix="santa-spec-"))
os.environ.setdefault("SANTA_PROFILES", str(_TMP / "profiles.json"))
os.environ["HYPOTHESIS_STORAGE_DIRECTORY"] = str(_TMP / "hypothesis")

from santa import memory  # noqa: E402

assert memory.load.__defaults__[0] != ROOT / "profiles.json", "would touch the real profiles.json"

GOLDEN = [json.loads(line) for line in (Path(__file__).parent / "golden.jsonl").read_text().splitlines()]
STORED = [r for r in GOLDEN if r["source"].startswith("stored:")]
E4B_V1 = [r for r in GOLDEN if r["source"] == "stageA:e4b-v1"]


def _chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class FakeClient:
    """client.chat.completions.create for streamed (Santa) and plain (extractor / warm-up) calls.
    replies: str | Exception per streamed call (the last one repeats). Every call is recorded in .calls."""

    def __init__(self, replies=("Ho ho ho! Hello there!",), extract='{"facts": []}', chunk=3):
        self.replies, self.extract, self.chunk = list(replies), extract, chunk
        self.calls, self.warm_calls = [], []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **opts):
        def create(**kw):
            self.warm_calls.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="h"))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def _create(self, **kw):
        self.calls.append(kw)
        if kw.get("stream"):
            r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
            if isinstance(r, Exception):
                raise r
            return iter([_chunk(r[i:i + self.chunk]) for i in range(0, len(r), self.chunk)])
        if isinstance(self.extract, Exception):
            raise self.extract
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.extract))])

    @property
    def santa_calls(self):
        return [c for c in self.calls if c.get("stream")]
