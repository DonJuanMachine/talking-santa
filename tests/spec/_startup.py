"""Start the app the way `python -m santa.web` does, without binding a socket (P7-4).

launch() runs santa.web.__main__.main(argv) with uvicorn.run replaced by a recorder, so every start-up guard in main()
runs (PIN length, certificate files, bind address, TLS and proxy-header arguments) and the test gets the app and the
keyword arguments uvicorn would have received. create_app is the real one; it loads no model until the app's
lifespan starts, which only a TestClient does.

`engines` / `overrides` let the network tests put the Stage H fakes and fast timings into the app main() built.
They may not touch any setting a start-up guard decides (asserted below), so what is tested is main()'s decision.
"""
import os
from dataclasses import replace

import uvicorn

from santa.web import server

GUARDED = {"host", "pin", "cert_file", "key_file", "allowed_hosts", "port"}


def launch(monkeypatch, argv, pin=None, lan=("santa-mac.local", "192.168.1.20"), engines=None, overrides=None,
           calls=None):
    """Run main(argv). Returns the recorded uvicorn.run calls: [(app, kwargs)], also appended to `calls` if given (so
    a test can check the list after main() refused with SystemExit).
    The process environment is restored by monkeypatch afterwards (main() and the module import both touch it)."""
    assert not GUARDED & set(overrides or {}), "a test may not override what the start-up guards decide"
    for k in ("HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "SANTA_PIN", "SANTA_PORT", "SANTA_ALERTS", "SANTA_HOSTS"):
        if k in os.environ:
            monkeypatch.setenv(k, os.environ[k])      # recorded, so teardown puts it back whatever main() does
        else:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("SANTA_PIN", raising=False)
    monkeypatch.delenv("SANTA_PORT", raising=False)
    monkeypatch.setenv("SANTA_ALERTS", "0")           # no macOS dialog from a test (the owner's own switch)
    if pin is not None:
        monkeypatch.setenv("SANTA_PIN", pin)

    import santa.web.__main__ as entry               # imported here, inside the env snapshot (it sets HF defaults)
    calls = [] if calls is None else calls
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    monkeypatch.setattr(entry, "_lan_names", lambda: list(lan))   # no scutil, no socket
    if engines or overrides:
        real = server.create_app

        def create_app(s, *a, **kw):
            return real(replace(s, **(overrides or {})), *a, **{**(engines or {}), **kw})
        monkeypatch.setattr(server, "create_app", create_app)
    entry.main(list(argv))
    return calls


def cert_files(tmp_path, cert=True, key=True):
    c, k = tmp_path / "santa.pem", tmp_path / "santa-key.pem"
    if cert:
        c.write_text("not a real certificate: main() only checks that the file exists\n")
    if key:
        k.write_text("not a real key\n")
    return c, k
