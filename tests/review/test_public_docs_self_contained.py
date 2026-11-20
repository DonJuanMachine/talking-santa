"""Public docs must make sense from the GitHub page alone: no pointers into the private notes/ folder and no review
IDs (P4-1, F5, ...) that are only defined there. docs/history/ is a development log and is exempt."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = sorted(
    [ROOT / n for n in ("README.md", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md")]
    + list((ROOT / "docs").glob("*.md"))
    + [ROOT / "local.example" / "README.md"]
    + list((ROOT / ".github").rglob("*.md"))
)
REVIEW_ID = re.compile(r"\bP\d+[a-z]?-\d+[a-z]?\b|\bF\d+[a-z]?\b")
PRIVATE_POINTERS = ("public-release checklist", "notes/")


@pytest.mark.parametrize("path", PUBLIC, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_review_ids(path):
    hits = [f"{path.name}:{i}: {m.group(0)}" for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            for m in REVIEW_ID.finditer(line)]
    assert not hits, hits


@pytest.mark.parametrize("path", PUBLIC, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_pointers_into_private_notes(path):
    text = path.read_text(encoding="utf-8")
    assert not [p for p in PRIVATE_POINTERS if p in text]
