"""The README's "How Santa was tested" section exists, the filter bullet links to it, and every number in it matches
the file it describes, so the summary cannot drift from the benchmark, the stored replies or the CHANGELOG."""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
HEAD = "## How Santa was tested\n"
CHANGELOG = " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split())


def _section():
    assert HEAD in README
    return " ".join(README.split(HEAD, 1)[1].split("\n## ", 1)[0].split())


def _bench_len(name):
    tree = ast.parse((ROOT / "evals/bench.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return len(node.value.elts)
    raise AssertionError(name)


def test_the_filter_bullet_links_to_the_section():
    intro = README.split("## What you need")[0]
    assert "(#how-santa-was-tested)" in intro


def test_benchmark_counts_match_the_benchmark():
    import json
    cases = len(json.loads((ROOT / "evals/cases.json").read_text())["cases"])
    s = _section()
    assert f"{cases} single-turn cases" in s
    assert f"{_bench_len('SCENARIOS')} multi-turn conversations" in s
    assert f"{_bench_len('EXTRACTION_CASES')} memory cases" in s


def test_stored_reply_count_matches_the_fixture():
    n = sum(1 for line in (ROOT / "tests/spec/golden.jsonl").read_text().splitlines() if line.strip())
    assert f"{n:,} stored model replies" in _section()


@pytest.mark.parametrize("phrase", ["182 short conversations", "100 gift requests", "44 claims", "18 with a wish list",
                                    "20 direct"])
def test_gap_probe_numbers_match_the_changelog(phrase):
    assert phrase in _section() and phrase in CHANGELOG


def test_section_says_what_was_not_tested():
    s = _section()
    assert "not been measured" in s and re.search(r"outside (expert|reviewer)", s)
