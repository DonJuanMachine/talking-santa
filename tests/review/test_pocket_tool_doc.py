"""The README sends users to tools/probes/j1_audition.py pocket-fetch for Pocket TTS. Its docstring (also what its
help command prints) must agree with the README: the project venv after `pip install pocket-tts`, not a second venv."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ast.get_docstring(ast.parse((ROOT / "tools/probes/j1_audition.py").read_text(encoding="utf-8")))


def test_no_second_venv():
    assert "talking-santa-j" not in DOC


def test_points_at_the_readme_install():
    assert "pip install pocket-tts" in DOC and "README" in DOC
