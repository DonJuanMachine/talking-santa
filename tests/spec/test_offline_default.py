"""`python -m santa.web` must not contact Hugging Face unless the owner allows it (docs claims check N1/N5).

Each case starts a fresh interpreter, because huggingface_hub reads these variables once, at import. Nothing here
loads a model or touches the network."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

PROBE = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import santa.web.__main__ as m            # the way `python -m santa.web` imports it
out = {"offline": os.environ.get("HF_HUB_OFFLINE"), "telemetry": os.environ.get("HF_HUB_DISABLE_TELEMETRY")}
if sys.argv[2] == "load":
    m.load_settings_env()                  # what main() does before it reads any setting
    out["after_load"] = os.environ.get("HF_HUB_OFFLINE")
    out["after_load_telemetry"] = os.environ.get("HF_HUB_DISABLE_TELEMETRY")
try:
    import huggingface_hub.constants as c
    out["hub_constant"] = bool(c.HF_HUB_OFFLINE)
except ImportError:
    out["hub_constant"] = None
print(json.dumps(out))
"""


def _run(mode="import", shell=None, env_file=None):
    scratch = Path(tempfile.mkdtemp(prefix="santa-offline-"))
    local = scratch / "local"
    local.mkdir()
    if env_file is not None:
        (local / "santa.env").write_text(env_file)
    env = {"PATH": "/usr/bin:/bin", "SANTA_LOCAL_DIR": str(local), "SANTA_PROFILES": str(scratch / "profiles.json"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(shell or {})
    r = subprocess.run([sys.executable, "-c", PROBE, str(ROOT), mode], env=env, capture_output=True, text=True,
                       cwd=str(scratch), timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_importing_the_app_sets_offline_before_huggingface_hub_loads():
    out = _run()
    assert out["offline"] == "1"
    assert out["telemetry"] == "1"
    if importlib.util.find_spec("huggingface_hub") is not None:
        assert out["hub_constant"] is True


def test_a_value_exported_in_the_shell_wins():
    out = _run(shell={"HF_HUB_OFFLINE": "0", "HF_HUB_DISABLE_TELEMETRY": "0"})
    assert (out["offline"], out["telemetry"]) == ("0", "0")
    if importlib.util.find_spec("huggingface_hub") is not None:
        assert out["hub_constant"] is False


def test_santa_env_can_override_the_default_and_keeps_it_when_silent():
    out = _run("load", env_file="HF_HUB_OFFLINE=0\nSANTA_SLOW_S=10\n")
    assert out["offline"] == "1" and out["after_load"] == "0"          # the file allows it on purpose
    assert out["after_load_telemetry"] == "1"                            # not mentioned in the file: default stays
    quiet = _run("load", env_file="SANTA_SLOW_S=10\n")
    assert (quiet["after_load"], quiet["after_load_telemetry"]) == ("1", "1")
    no_file = _run("load")
    assert no_file["after_load"] == "1"


def test_shell_value_beats_santa_env():
    out = _run("load", shell={"HF_HUB_OFFLINE": "0"}, env_file="HF_HUB_OFFLINE=1\n")
    assert out["after_load"] == "0"
