"""local/: personal files (settings, Santa's picture, profiles) are found by name and never needed."""
import _support  # noqa: F401  (temp profiles; must come first)

import os

import pytest

from santa import local


def test_env_file_sets_missing_keys_and_never_overrides_the_shell(tmp_path, monkeypatch):
    f = tmp_path / "santa.env"
    f.write_text('# comment\n\nSANTA_T_A=1225\nexport SANTA_T_B="two words"\nSANTA_T_C=from-file\nnot a line\n')
    monkeypatch.setenv("SANTA_T_C", "from-shell")
    for k in ("SANTA_T_A", "SANTA_T_B"):
        monkeypatch.delenv(k, raising=False)
    try:
        assert sorted(local.load_env(f)) == ["SANTA_T_A", "SANTA_T_B"]
        assert os.environ["SANTA_T_A"] == "1225"
        assert os.environ["SANTA_T_B"] == "two words"
        assert os.environ["SANTA_T_C"] == "from-shell"
    finally:
        for k in ("SANTA_T_A", "SANTA_T_B"):
            os.environ.pop(k, None)


def test_missing_env_file_is_fine(tmp_path):
    assert local.load_env(tmp_path / "nope.env") == []


def test_santa_image_is_found_by_name_or_absent(tmp_path):
    assert local.santa_image(tmp_path) is None
    (tmp_path / "santa.png").write_bytes(b"x")
    assert local.santa_image(tmp_path) == tmp_path / "santa.png"
    (tmp_path / "santa.jpg").write_bytes(b"x")
    assert local.santa_image(tmp_path) == tmp_path / "santa.jpg"     # .jpg first


def test_profiles_move_to_local_but_an_old_root_file_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "ROOT", tmp_path)
    monkeypatch.setattr(local, "LOCAL_DIR", tmp_path / "local")
    assert local.profiles_path() == tmp_path / "local" / "profiles.json"
    (tmp_path / "profiles.json").write_text("{}")
    assert local.profiles_path() == tmp_path / "profiles.json"
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "profiles.json").write_text("{}")
    assert local.profiles_path() == tmp_path / "local" / "profiles.json"


def test_call_page_serves_your_picture_else_the_drawing(tmp_path):
    from fastapi.testclient import TestClient
    from test_network_mode import app_for

    pic = tmp_path / "santa.jpg"
    pic.write_bytes(b"\xff\xd8\xff my santa")
    with TestClient(app_for(santa_image=pic)) as c:
        assert c.get("/santa-image").content == pic.read_bytes()
    with TestClient(app_for(santa_image=None)) as c:
        r = c.get("/santa-image")
        assert r.headers["content-type"].startswith("image/svg")


# ------------------------------------------------------------------------------- one settings parser (2026-11-10)
@pytest.mark.parametrize("line,value", [
    ("SANTA_GATE_LIMIT=10  # requests per minute", "10"),        # the template's inline comments
    ("SANTA_PIN=48#29x", "48#29x"),                               # a # inside a value is kept
    ("SANTA_PIN=           # required for --network", ""),        # an uncommented template line: empty
    ('SANTA_VOICE="am_santa:70, bm_fable:30"  # blend', "am_santa:70, bm_fable:30"),
    ("SANTA_PIN='a#b' # note", "a#b"),
    ("export SANTA_SPEED=0.9", "0.9"),
])
def test_read_env_handles_comments_quotes_and_hashes(tmp_path, line, value):
    f = tmp_path / "santa.env"
    f.write_text(f"# a comment line\n\n{line}\n")
    key = line.removeprefix("export ").split("=", 1)[0]
    assert local.read_env(f) == {key: value}


def test_read_env_skips_malformed_keys(tmp_path):
    f = tmp_path / "santa.env"
    f.write_text("SANTA OK=1\n$(touch x)=2\nSANTA_GOOD=3\n")
    assert local.read_env(f) == {"SANTA_GOOD": "3"}


def test_shell_exports_are_safe_to_eval_and_the_shell_wins(tmp_path, monkeypatch):
    import subprocess
    f = tmp_path / "santa.env"
    marker = tmp_path / "pwned"
    f.write_text(f"SANTA_EVIL=$(touch {marker})`touch {marker}`'\"; touch {marker}\n"
                 "SANTA_SHELL_WINS=from-file\nSANTA_LOCAL_DIR=/somewhere/else\nOTHER=not-santa\n")
    monkeypatch.setenv("SANTA_SHELL_WINS", "from-shell")
    out = local.shell_exports(f)
    assert "SANTA_LOCAL_DIR" not in out and "OTHER" not in out and "SANTA_SHELL_WINS" not in out
    r = subprocess.run(["bash", "-c", f'eval "$1"; printf "%s" "$SANTA_EVIL"', "_", out],
                       capture_output=True, text=True)
    assert r.returncode == 0 and not marker.exists()                     # nothing ran
    assert r.stdout == f"$(touch {marker})`touch {marker}`'\"; touch {marker}"   # the value arrived intact
    assert out.splitlines()[0] == f"LOCAL={local.LOCAL_DIR}" or out.startswith("LOCAL='")
