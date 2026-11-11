"""Claude Code must not read the private term files or the children's data (P10-4 follow-up). Checks rule text only."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_settings_deny_reading_the_private_term_files():
    deny = json.loads((ROOT / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert "Read(~/.santa-pii-terms.txt)" in deny
    assert "Read(~/.santa-pii-terms-cs.txt)" in deny
    assert "Read(./local/**)" in deny and "Read(./profiles.json*)" in deny
