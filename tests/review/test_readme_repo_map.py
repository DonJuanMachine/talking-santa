"""The README's "Layout" list names everything a visitor sees: every top-level tracked entry, every module directly in
santa/, and every direct child of docs/ and evals/. A new file or folder there must get a line in the map."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
MAP = README.split("\nLayout:\n", 1)[1].split("\n### ", 1)[0]
NAMED = set(re.findall(r"`([^`]+)`", MAP))


def _tracked():
    if not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def _children(paths, parent=""):
    """Direct children of parent (folders end in '/')."""
    out = set()
    for p in paths:
        if not p.startswith(parent):
            continue
        rest = p[len(parent):]
        head, sep, _ = rest.partition("/")
        out.add(head + "/" if sep else head)
    return out


def _missing(parent, names):
    return sorted(n for n in names if n not in NAMED and parent + n not in NAMED)


def test_every_top_level_entry_is_in_the_map():
    assert _missing("", _children(_tracked()) - {"README.md"}) == []


def test_every_santa_module_is_in_the_map():
    mods = {n for n in _children(_tracked(), "santa/") if n.endswith(".py")}
    assert _missing("santa/", mods) == []


@pytest.mark.parametrize("folder", ["docs/", "evals/"])
def test_every_docs_and_evals_child_is_in_the_map(folder):
    assert _missing(folder, _children(_tracked(), folder)) == []


def test_map_names_nothing_that_is_not_tracked():
    tracked = _tracked()
    known = set(tracked) | {str(Path(p).parent) + "/" for p in tracked} | {
        str(q) + "/" for p in tracked for q in Path(p).parents}
    paths = [n for n in NAMED if "/" in n and not n.startswith(("local/", "~")) and " " not in n
             and not n.endswith("out/")]
    stale = sorted(n for n in paths if n not in known and n.rstrip("/") not in known
                   and not any(k.endswith("/" + n) or k.endswith("/" + n.rstrip("/")) for k in known))
    assert stale == []
