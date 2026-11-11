"""Suite-wide isolation (P6-8): whatever the shell exports, every test run uses a fresh temp SANTA_LOCAL_DIR and
SANTA_PROFILES. The assignment is at import time on purpose: santa.config / santa.memory bind these paths when
they are first imported, which happens during collection, before any fixture runs. The session fixture then
checks that nothing moved them."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._real_paths import real_profiles_paths  # noqa: E402

_ISO = Path(tempfile.mkdtemp(prefix="santa-tests-")).resolve()
os.environ["SANTA_LOCAL_DIR"] = str(_ISO / "local")
os.environ["SANTA_PROFILES"] = str(_ISO / "profiles.json")


@pytest.fixture(scope="session", autouse=True)
def _isolated_local_and_profiles():
    from santa import config, local
    tmp = Path(tempfile.gettempdir()).resolve()
    prof, loc = config.PROFILES_PATH.resolve(), local.LOCAL_DIR.resolve()
    assert prof not in real_profiles_paths(), "tests would touch the real profiles file"
    assert tmp in prof.parents, "profiles path is not under the temp dir"
    assert loc != (local.ROOT / "local").resolve() and tmp in loc.parents, "tests would touch the real local/ folder"
    yield
