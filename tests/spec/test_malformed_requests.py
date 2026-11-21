"""Malformed requests are refused quietly, not with an unhandled error (VulnHunter run 2).

An unhandled exception makes uvicorn write a full traceback to the log for each request, so anyone who can reach the
server can grow the log at will, and it skips the normal answer.

- VULN-021: an Origin that urlsplit cannot parse (`http://[`) made origin_ok raise before the PIN check.
- VULN-019: `/static/%00` made Path.resolve raise "embedded null character" (a 5 KB traceback per request).
"""
import _support  # noqa: F401  (temp profiles; must come first)

import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from santa.web.access import origin_ok
from test_network_mode import WSS, app_for, lan_app, lan_client

BAD_ORIGINS = ["http://[", "http://[::1", "https://[not-an-ip]"]


@pytest.mark.parametrize("origin", BAD_ORIGINS)
def test_an_unparseable_origin_is_simply_not_this_server(origin):
    assert origin_ok(origin, "testserver") is False


@pytest.mark.parametrize("origin", BAD_ORIGINS)
def test_a_websocket_with_an_unparseable_origin_is_refused_without_a_traceback(monkeypatch, tmp_path, caplog, origin):
    app = lan_app(monkeypatch, tmp_path)
    caplog.set_level(logging.ERROR)
    with pytest.raises(WebSocketDisconnect) as e:
        with lan_client(app).websocket_connect(WSS, headers={"origin": origin}) as ws:
            ws.receive_json()
    assert e.value.code == 1008                       # refused like any other foreign origin
    assert not [r for r in caplog.records if r.exc_info]


# ------------------------------------------------------------------------------- VULN-019: NUL in a static file name
@pytest.mark.parametrize("name", ["%00", "app.js%00", "%00.png"])
def test_a_static_name_with_a_nul_byte_is_not_found(name):
    with TestClient(app_for()) as c:                  # default mode: any local process, no PIN
        r = c.get(f"/static/{name}")
    assert r.status_code == 404
