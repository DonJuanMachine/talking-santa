"""Security alert: raised on lockouts, the rate limit and unknown hosts; Stop Santa only when a grown-up chooses it.

A fake dialog stands in for the macOS one, so no window ever opens during tests.
"""
import _support  # noqa: F401  (temp profiles; must come first)

from fastapi.testclient import TestClient

from santa.web.access import Gate
from santa.web.alerts import KEEP, STOP, Alerter
from test_network_mode import PIN, app_for
from test_stage_h import fast_settings


class FakeDialog:
    def __init__(self, answer):
        self.answer, self.shown = answer, []

    def __call__(self, message, timeout_s):
        self.shown.append(message)
        return self.answer


def alerter(answer, clock=None):
    stops = []
    d = FakeDialog(answer)
    a = Alerter(enabled=True, show=d, on_stop=lambda: stops.append(1), background=False,
                clock=clock or (lambda: 0.0))
    return a, d, stops


def test_stop_santa_stops_and_keep_running_or_no_answer_does_not():
    a, d, stops = alerter(STOP)
    assert a.alert("x") and stops == [1] and "Stop Santa now?" in d.shown[0]
    for answer in (KEEP, None):                      # None: timed out or closed
        a, _, stops = alerter(answer)
        a.alert("x")
        assert stops == []


def test_one_alert_per_cooldown():
    now = [0.0]
    a, d, _ = alerter(KEEP, clock=lambda: now[0])
    assert a.alert("first")
    now[0] = 599
    assert not a.alert("second")
    now[0] = 600
    assert a.alert("third")
    assert len(d.shown) == 2


def test_disabled_alerter_never_shows():
    d = FakeDialog(STOP)
    a = Alerter(enabled=False, show=d, background=False)
    assert not a.alert("x") and d.shown == []


def test_lockout_and_rate_limit_raise_alerts():
    seen = []
    now = [0.0]
    g = Gate(fast_settings(host="0.0.0.0", pin=PIN, pin_max_tries=2, gate_limit_per_min=3),
             clock=lambda: now[0], on_alert=seen.append)
    g.try_pin("10.0.0.1", "000000"); g.try_pin("10.0.0.1", "000000")
    assert len(seen) == 1 and "locked out" in seen[0]
    for _ in range(5):
        g.admit()
    assert len(seen) == 2 and "tries in one minute" in seen[1]      # once per limited stretch, not per request


def test_unknown_host_raises_an_alert_in_the_app():
    a, d, stops = alerter(KEEP)
    with TestClient(app_for(alerter=a), client=("127.0.0.1", 50000)) as c:
        assert c.get("/", headers={"host": "evil.example"}).status_code == 400
    assert len(d.shown) == 1 and "DNS rebinding" in d.shown[0] and stops == []
