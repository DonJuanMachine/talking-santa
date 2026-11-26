"""The shipped voice is Kyutai Pocket TTS with the built-in voice stuart_bell; SANTA_TTS=kokoro switches to Kokoro
am_michael. The settings, the start script and the docs must all name the same default.

Settings read the environment when the module is imported, so each case starts a fresh interpreter with a clean
environment and an empty local folder. Nothing here loads a voice model."""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from santa.web.settings import Settings
s = Settings()
print(json.dumps({"engine": s.tts_engine, "voice": s.voice}))
"""


def _settings(**extra):
    local = Path(tempfile.mkdtemp(prefix="santa-voice-")) / "local"
    local.mkdir()
    env = {"PATH": "/usr/bin:/bin", "SANTA_LOCAL_DIR": str(local), "PYTHONDONTWRITEBYTECODE": "1", **extra}
    out = subprocess.run([sys.executable, "-c", PROBE, str(ROOT)], env=env, capture_output=True, text=True,
                         timeout=60, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize("extra,engine,voice", [
    ({}, "pocket", "stuart_bell"),
    ({"SANTA_TTS": "pocket"}, "pocket", "stuart_bell"),
    ({"SANTA_TTS": "kokoro"}, "kokoro", "am_michael"),
    ({"SANTA_VOICE": "anna"}, "pocket", "anna"),
    ({"SANTA_TTS": "kokoro", "SANTA_VOICE": "am_santa:70,bm_fable:30"}, "kokoro", "am_santa:70,bm_fable:30"),
], ids=["default", "pocket", "kokoro", "own-pocket-voice", "own-kokoro-blend"])
def test_settings_default_voice(extra, engine, voice):
    assert _settings(**extra) == {"engine": engine, "voice": voice}


def test_start_script_agrees():
    sh = (ROOT / "scripts/start-santa.sh").read_text()
    assert 'TTS="${SANTA_TTS:-pocket}"' in sh
    assert "Pocket TTS (${SANTA_VOICE:-stuart_bell})" in sh
    assert "Kokoro (${SANTA_VOICE:-am_michael})" in sh


def test_docs_agree():
    conf = (ROOT / "docs/configuration.md").read_text()
    assert re.search(r"^\| `SANTA_TTS` \| `pocket` \|", conf, re.M)
    assert re.search(r"^\| `SANTA_VOICE` \| `stuart_bell` \(`am_michael` when `SANTA_TTS=kokoro`\) \|", conf, re.M)
    readme = (ROOT / "README.md").read_text()
    assert "Kyutai Pocket TTS, voice `stuart_bell`, by default" in readme
    assert "j1_audition.py pocket-fetch" in readme.split("## One-time install", 1)[1].split("\n## ", 1)[0]
    example = (ROOT / "local.example/santa.env.example").read_text()
    assert "# SANTA_TTS=pocket" in example and "# SANTA_VOICE=stuart_bell" in example


def test_pocket_is_installed_with_the_web_extra():
    assert '"pocket-tts==4.0.1"' in (ROOT / "pyproject.toml").read_text()
