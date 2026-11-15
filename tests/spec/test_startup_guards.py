"""P7-4 / invariant I5: the start-up guards in santa/web/__main__.py.

main() is the only place that requires a PIN and HTTPS files before binding 0.0.0.0, and that passes
proxy_headers=False. It runs here with uvicorn.run replaced by a recorder (tests/spec/_startup.py): nothing binds a
socket, no model loads, no network.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import pytest

from _startup import cert_files, launch

GOOD_PIN = "246813"


def _settings(app):
    return app.state.engines.s


def _refused(excinfo):
    """sys.exit("message") exits with status 1; sys.exit(0) / sys.exit() would be a silent success."""
    code = excinfo.value.code
    return (isinstance(code, str) and code.strip()) or (isinstance(code, int) and code != 0)


# ------------------------------------------------------------------------------------------- default start
def test_a_plain_start_binds_127_0_0_1_without_tls_and_without_proxy_headers(monkeypatch):
    calls = launch(monkeypatch, [])
    assert len(calls) == 1
    app, kw = calls[0]
    assert kw["host"] == "127.0.0.1"
    assert kw["proxy_headers"] is False
    assert "ssl_certfile" not in kw and "ssl_keyfile" not in kw
    s = _settings(app)
    assert s.host == "127.0.0.1" and not s.network


def test_a_plain_start_ignores_a_pin_and_still_binds_127_0_0_1(monkeypatch, tmp_path):
    """A PIN in local/santa.env and certificate files on disk must not open the server without --network."""
    cert, key = cert_files(tmp_path)
    app, kw = launch(monkeypatch, ["--cert", str(cert), "--key", str(key)], pin=GOOD_PIN)[0]
    assert kw["host"] == "127.0.0.1" and "ssl_certfile" not in kw
    assert not _settings(app).network


# ------------------------------------------------------------------------------------------- --network refused
@pytest.mark.parametrize("pin", [None, "", "12345", "      ", "  12345  ", "\t1234\n"],
                         ids=["unset", "empty", "5-chars", "spaces", "5-chars-padded", "4-chars-whitespace"])
def test_network_without_a_6_character_pin_exits_non_zero(monkeypatch, tmp_path, pin):
    cert, key = cert_files(tmp_path)
    calls = []
    with pytest.raises(SystemExit) as e:
        launch(monkeypatch, ["--network", "--cert", str(cert), "--key", str(key)], pin=pin, calls=calls)
    assert _refused(e) and "PIN" in str(e.value.code)
    assert calls == []                                    # nothing would have bound


@pytest.mark.parametrize("have", [(False, True), (True, False), (False, False)],
                         ids=["no-cert", "no-key", "neither"])
def test_network_without_both_certificate_files_exits_non_zero(monkeypatch, tmp_path, have):
    cert, key = cert_files(tmp_path, *have)
    calls = []
    with pytest.raises(SystemExit) as e:
        launch(monkeypatch, ["--network", "--cert", str(cert), "--key", str(key)], pin=GOOD_PIN, calls=calls)
    assert _refused(e) and "certificate" in str(e.value.code)
    assert calls == []
    missing = [str(p) for p, ok in zip((cert, key), have) if not ok]
    assert all(m in str(e.value.code) for m in missing)


def test_network_refuses_a_directory_where_a_certificate_file_should_be(monkeypatch, tmp_path):
    cert, key = cert_files(tmp_path, key=False)
    key.mkdir()
    calls = []
    with pytest.raises(SystemExit) as e:
        launch(monkeypatch, ["--network", "--cert", str(cert), "--key", str(key)], pin=GOOD_PIN, calls=calls)
    assert _refused(e) and calls == []


# ------------------------------------------------------------------------------------------- --network accepted
def test_a_good_network_start_passes_the_certificate_files_and_proxy_headers_off(monkeypatch, tmp_path):
    cert, key = cert_files(tmp_path)
    calls = launch(monkeypatch, ["--network", "--cert", str(cert), "--key", str(key)], pin=GOOD_PIN,
                   lan=("santa-mac.local", "192.168.1.20"))
    assert len(calls) == 1
    app, kw = calls[0]
    assert kw["host"] == "0.0.0.0"
    assert kw["ssl_certfile"] == str(cert) and kw["ssl_keyfile"] == str(key)
    assert kw["proxy_headers"] is False
    s = _settings(app)
    assert s.network and s.pin == GOOD_PIN
    assert s.cert_file == cert and s.key_file == key
    assert set(s.allowed_hosts) == {"127.0.0.1", "localhost", "::1", "santa-mac.local", "192.168.1.20"}


def test_a_good_network_start_strips_the_pin(monkeypatch, tmp_path):
    cert, key = cert_files(tmp_path)
    app, _ = launch(monkeypatch, ["--network", "--cert", str(cert), "--key", str(key)], pin=f"  {GOOD_PIN}\n")[0]
    assert _settings(app).pin == GOOD_PIN
