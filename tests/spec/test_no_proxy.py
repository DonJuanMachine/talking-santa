"""P2-1: the model clients must never use an HTTP proxy from the environment (invariant I1: nothing leaves the Mac).

Two local listeners on 127.0.0.1: one stands in for a proxy (named in HTTP_PROXY, HTTPS_PROXY and ALL_PROXY), the
other for the model runner. Each app client sends requests to the runner. The proxy must see no connection.
No external network.
"""
import _support  # noqa: F401  (temp profiles; must come first)

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from santa import config
from santa.brain import Santa
from santa.web.brain_adapter import SantaBrain

_REPLY = json.dumps({
    "id": "x", "object": "chat.completion", "created": 0, "model": "m",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Ho"}, "finish_reason": "stop"}],
}).encode()

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


class _Listener(ThreadingHTTPServer):
    """Counts every accepted connection. Answers each request with `status` and `body`."""

    daemon_threads = True

    def __init__(self, status, body):
        self.status, self.body, self.connections, self.paths = status, body, 0, []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                server.paths.append(self.path)
                self.send_response(server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(server.body)))
                self.end_headers()
                self.wfile.write(server.body)

            do_GET = do_POST = do_CONNECT = _answer

            def log_message(self, *a):
                pass

        super().__init__(("127.0.0.1", 0), Handler)

    def verify_request(self, request, client_address):
        self.connections += 1
        return True

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


@pytest.fixture
def listeners(monkeypatch):
    proxy = _Listener(502, b'{"error": "proxy"}')
    runner = _Listener(200, _REPLY)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (proxy, runner)]
    for t in threads:
        t.start()
    for name in _PROXY_VARS:
        monkeypatch.setenv(name, proxy.url)
        monkeypatch.setenv(name.lower(), proxy.url)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    base_url = runner.url + "/engines/v1"
    monkeypatch.setattr(config, "BASE_URL", base_url)
    try:
        yield proxy, runner, base_url
    finally:
        for s in (proxy, runner):
            s.shutdown()
            s.server_close()


def _check(proxy, runner, client, warm_up):
    """Two requests: the app's warm-up (a with_options copy) and a plain call on the client itself."""
    warmed = warm_up()
    try:
        out = client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}], max_tokens=1)
        content = out.choices[0].message.content
    except Exception as e:
        content = f"{type(e).__name__}: {e}"
    assert proxy.connections == 0, f"{proxy.connections} connection(s) went to the proxy: {proxy.paths}"
    assert runner.connections >= 1 and len(runner.paths) == 2
    assert warmed and content == "Ho"


def test_santa_client_ignores_proxy_env(listeners):
    proxy, runner, base_url = listeners
    santa = Santa(base_url=base_url, profiles={})
    _check(proxy, runner, santa.client, santa.warm_up)


def test_web_brain_client_ignores_proxy_env(listeners):
    proxy, runner, _ = listeners
    brain = SantaBrain(profiles={})
    _check(proxy, runner, brain.client, brain.warm_up)
