"""Run only by test_isolation.py (not collected by name). Writes nothing."""
import tests.spec._support  # noqa: F401  (what spec tests import first)
from santa import config, local
from tests._real_paths import real_profiles_paths


def test_probe():
    assert config.PROFILES_PATH.resolve() not in real_profiles_paths()
    assert local.LOCAL_DIR.resolve() != (local.ROOT / "local").resolve()
