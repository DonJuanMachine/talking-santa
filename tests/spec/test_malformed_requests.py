"""Malformed requests are refused quietly, not with an unhandled error (VulnHunter run 2).

An unhandled exception makes uvicorn write a full traceback to the log for each request, so anyone who can reach the
server can grow the log at will, and it skips the normal answer.

- VULN-021: an Origin that urlsplit cannot parse (`http://[`) made origin_ok raise before the PIN check.
- VULN-019: `/static/%00` made Path.resolve raise "embedded null character" (a 5 KB traceback per request).
- VULN-020: deeply nested JSON on the WebSocket raised RecursionError (sooner on CPython 3.12), which escaped `except ValueError`
  and ended the call page's socket with a traceback.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import json
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from santa.web.access import origin_ok
from test_network_mode import WSS, app_for, lan_app, lan_client, local, read_until  # noqa: F401  (local: fixture)

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


# ------------------------------------------------------------------------------- VULN-020: deeply nested JSON
DEEP = "[" * 200_000


def test_deeply_nested_json_is_ignored_and_the_call_page_keeps_working(local):
    with local.websocket_connect("/ws") as ws:
        ws.send_text(DEEP)
        ws.send_json({"type": "hello"})
        assert read_until(ws, "state")                # the socket survived and still answers


def test_a_recursion_error_from_the_json_parser_is_ignored_too(monkeypatch, local):
    """The parser's RecursionError depends on the Python version and the nesting depth (3.12, the documented runtime,
    raises it sooner). Simulate it so the test means the same on every version."""
    from santa.web import server
    real = json.loads

    def loads(text, *a, **kw):
        if isinstance(text, str) and text.startswith("[[[["):
            raise RecursionError("maximum recursion depth exceeded while decoding a JSON array")
        return real(text, *a, **kw)
    monkeypatch.setattr(server.json, "loads", loads)
    with local.websocket_connect("/ws") as ws:
        ws.send_text(DEEP)
        ws.send_json({"type": "hello"})
        assert read_until(ws, "state")
