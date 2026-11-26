"""The age range is stated the same way everywhere it appears: the persona prompt Santa is given, the README, the
architecture and the benchmark description. The prompt and the benchmark were built for ages 2 to 5, so the docs must
not promise a wider range than Santa is told to talk to."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RANGE = re.compile(r"ages (\d+) to (\d+)")
FILES = ["santa/persona.py", "README.md", "docs/architecture.md", "docs/model-selection.md"]


def _ranges(rel):
    text = " ".join((ROOT / rel).read_text(encoding="utf-8").split())
    return set(RANGE.findall(text))


def test_the_persona_prompt_says_2_to_5():
    assert _ranges("santa/persona.py") == {("2", "5")}


@pytest.mark.parametrize("rel", FILES[1:])
def test_docs_state_the_same_range_as_the_prompt(rel):
    """A doc may leave the range out (the README has named no ages since 2026-11-22: the range was not backed by
    testing), but any range it states must be the prompt's."""
    assert _ranges(rel) <= _ranges("santa/persona.py")
