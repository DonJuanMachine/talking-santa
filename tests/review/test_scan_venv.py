"""scripts/security-scan.sh runs Snyk's pip scan with the project's own Python environment.

Snyk needs the dependencies installed. The README creates the environment at ~/.venvs/talking-santa-h (SANTA_PYTHON
overrides it), and run-web.sh and start-santa.sh use exactly that default. The scan used to look for a repo-local
.venv/ that the documented setup never creates, so Snyk fell back to the system python3 and failed
("Required packages missing").
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = (ROOT / "scripts" / "security-scan.sh").read_text(encoding="utf-8")


def _default_python(script: str) -> str:
    text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
    return re.search(r'^PY="(\$\{SANTA_PYTHON:-[^"]+\})"', text, re.M).group(1)


def test_the_launch_scripts_agree_on_the_default():
    assert _default_python("run-web.sh") == _default_python("start-santa.sh")


def test_snyk_uses_the_same_python_as_the_launch_scripts():
    line = next(l for l in SCAN.splitlines() if l.startswith("SNYK_PY="))
    assert f'SNYK_PY="{_default_python("run-web.sh")}"' in line, line


def test_no_repo_local_venv():
    assert ".venv/bin/python" not in SCAN
