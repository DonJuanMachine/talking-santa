"""Every voice engine the code accepts has a row in the Models tables (README and architecture), so the developer and
source of every model a user can choose are listed. The engines come from santa/web/server.py's SANTA_TTS check."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINES = re.search(r'tts_engine not in \(([^)]*)\)', (ROOT / "santa/web/server.py").read_text()).group(1)
ROWS = {"kokoro": ("Kokoro-82M", "hexgrad/Kokoro-82M"), "pocket": ("Pocket TTS", "kyutai-labs/pocket-tts")}


def _section(path: Path, heading: str) -> str:
    return path.read_text(encoding="utf-8").split(heading + "\n", 1)[1].split("\n## ", 1)[0]


DOCS = [(ROOT / "README.md", "## Models"), (ROOT / "docs/architecture.md", "## 7. Models")]


def test_the_known_engines_are_still_the_ones_the_code_accepts():
    assert set(re.findall(r'"(\w+)"', ENGINES)) == set(ROWS)


@pytest.mark.parametrize("path,heading", DOCS, ids=["README", "architecture"])
def test_every_voice_engine_has_a_row(path, heading):
    rows = [line for line in _section(path, heading).splitlines() if line.startswith("|")]
    for name, link in ROWS.values():
        assert any(name in r and link in r for r in rows), name


@pytest.mark.parametrize("path,heading", DOCS, ids=["README", "architecture"])
def test_no_stale_model_count(path, heading):
    assert "All four are" not in _section(path, heading)
