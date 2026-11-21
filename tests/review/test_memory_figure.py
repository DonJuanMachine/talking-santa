"""README "What you need" gives the language model's memory use as measured in docs/model-selection.md, not an
estimate from the file size. The benchmark measured the model server for the default model during a run; the README
must state that figure (rounded) and point at where it comes from."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELECTION = (ROOT / "docs" / "model-selection.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _measured_gb() -> float:
    row = next(line for line in SELECTION.splitlines() if line.startswith("| Model server memory during the run"))
    return float(re.search(r"~([\d.]+) GB", row.split("|")[2]).group(1))     # first column: the default model


def _need() -> str:
    return " ".join(README.split("## What you need", 1)[1].split("\n## ", 1)[0].split())


def test_readme_states_the_measured_figure():
    assert f"about {round(_measured_gb())} GB" in _need(), _measured_gb()


def test_readme_names_the_source_of_the_figure():
    assert "docs/model-selection.md" in _need()


def test_the_old_estimate_is_gone():
    assert "about 5 GB" not in _need()
