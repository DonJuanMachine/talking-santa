"""Who may use the call page.

- Host allowlist (every request, every mode): the server only answers to its own names (127.0.0.1, localhost and,
  with --network, this Mac's .local name and Wi-Fi address). This blocks DNS rebinding, where a website points its
  own domain at 127.0.0.1 so the browser treats Santa as part of that website.
- This Mac (loopback) is never asked for the PIN. Other devices enter it once; they then get a cookie that is valid
  until the server restarts.
- Wrong PINs: after `pin_max_tries` from one device, that device is locked out. Each lockout is longer than the last
  (`pin_lockouts`, e.g. 1 min, 5 min, 30 min).
- Rate limit: PIN tries (POST /unlock) from devices that have not entered the PIN are limited to
  `gate_limit_per_min` a minute, all devices together, and `gate_limit_per_device` from any one device. A PIN guesser
  using many addresses is held to the shared rate, and one device cannot use it all up and lock the family out
  (VULN-003). The PIN page, other paths and refused WebSockets are not counted, nor is a device that is locked out.
  This Mac and unlocked devices are never counted.
- The WebSocket only accepts pages served by this server: Origin must equal Host, and Host must be on the allowlist.
- PIN tries (POST /unlock) from another website are refused before they are counted, so a site open in a family
  browser cannot lock that device out with wrong PINs (VULN-004).
"""
import collections
import hmac
import logging
import secrets
import time
from html import escape
from urllib.parse import urlsplit

from .settings import Settings, is_loopback

COOKIE = "santa_unlock"
log = logging.getLogger("santa.web")


def host_name(host_header: str | None) -> str | None:
    """'System.local:8765' -> 'system.local', '[::1]:8765' -> '::1'. None if missing or malformed."""
    if not host_header:
        return None
    try:
        return urlsplit("//" + host_header).hostname
    except ValueError:
        return None


class Gate:
    def __init__(self, s: Settings, clock=time.monotonic, on_alert=None):
        self.s = s
        self.clock = clock
        self.on_alert = on_alert or (lambda reason: None)     # security alert (santa/web/alerts.py)
        # Random per server start: a cookie cannot be forged from the PIN, and a restart signs everyone out.
        self._token = secrets.token_urlsafe(32)
        # client ip -> (wrong tries since the last lockout, lockouts so far, locked until)
        self._fails: dict[str, tuple[int, int, float]] = {}
        self._recent: collections.deque[float] = collections.deque()   # times of counted PIN tries, all devices
        self._recent_by_device: dict[str, collections.deque[float]] = {}  # the same, per device
        self._limited_since: float | None = None
        self.hosts = {h.lower() for h in (*s.allowed_hosts, *s.extra_hosts)}

    @property
    def pin_required(self) -> bool:
        return bool(self.s.pin)

    # ------------------------------------------------------------------------------------------- who is asking
    def host_ok(self, host_header: str | None) -> bool:
        return host_name(host_header) in self.hosts

    def allowed(self, client_host: str | None, cookies: dict) -> bool:
        if not self.pin_required or is_loopback(client_host):
            return True
        # bytes: a non-ASCII cookie must fail, not raise (compare_digest refuses non-ASCII str)
        return hmac.compare_digest(cookies.get(COOKIE, "").encode(), self._token.encode())

    # ------------------------------------------------------------------------------------------- rate limit
    def admit(self, client_host: str | None) -> bool:
        """Count one PIN try from a device that has not entered the PIN. False once the shared per-minute limit, or
        this device's share of it, is used."""
        now = self.clock()
        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        for key in list(self._recent_by_device):     # stays small: at most gate_limit_per_min entries a minute
            times = self._recent_by_device[key]
            while times and now - times[0] >= 60:
                times.popleft()
            if not times:
                del self._recent_by_device[key]
        mine = self._recent_by_device.get(client_host or "", collections.deque())
        if len(mine) >= self.s.gate_limit_per_device:
            return False                             # this device's share: no alert, its lockout already alerts
        if len(self._recent) >= self.s.gate_limit_per_min:
            if self._limited_since is None:
                self._limited_since = now
                log.warning("rate limit: more than %d requests in a minute from devices without the PIN",
                            self.s.gate_limit_per_min)
                self.on_alert(f"More than {self.s.gate_limit_per_min} tries in one minute from devices "
                              "that have not entered the PIN.")
            return False
        self._limited_since = None
        self._recent.append(now)
        mine.append(now)
        self._recent_by_device[client_host or ""] = mine
        return True

    # ------------------------------------------------------------------------------------------- PIN
    def locked_for(self, client_host: str) -> float:
        """Seconds this device must still wait, 0 if it may try."""
        _, _, until = self._fails.get(client_host, (0, 0, 0.0))
        return max(0.0, until - self.clock())

    def try_pin(self, client_host: str, pin: str) -> str | None:
        """The cookie value on a correct PIN, else None (and the wrong try is counted)."""
        if self.locked_for(client_host):
            return None
        if hmac.compare_digest(pin.strip().encode(), self.s.pin.encode()):
            self._fails.pop(client_host, None)
            return self._token
        n, lockouts, _ = self._fails.get(client_host, (0, 0, 0.0))
        n += 1
        until = 0.0
        if n >= self.s.pin_max_tries:
            steps = self.s.pin_lockouts
            until = self.clock() + steps[min(lockouts, len(steps) - 1)]     # longer each time
            lockouts, n = lockouts + 1, 0
            log.warning("PIN lockout %d for a device (%d wrong tries)", lockouts, self.s.pin_max_tries)
            self.on_alert(f"A device entered {self.s.pin_max_tries} wrong PINs and is locked out "
                          f"({wait_text(until - self.clock())}).")
        self._fails[client_host] = (n, lockouts, until)
        return None


def origin_ok(origin: str | None, host: str | None) -> bool:
    """A browser always sends Origin on a WebSocket; it must be this server. No Origin (not a browser) is allowed:
    the PIN or loopback check still applies after this."""
    if not origin:
        return True
    try:
        netloc = urlsplit(origin).netloc
    except ValueError:                               # e.g. "http://[": not this server; refuse quietly (VULN-021)
        return False
    return bool(host) and netloc.lower() == host.lower()


def from_another_site(origin: str | None, fetch_site: str | None, host: str | None) -> bool:
    """A form post made by another website (VULN-004): a foreign or `null` Origin, or Sec-Fetch-Site: cross-site.
    No Origin (curl, an old browser) is not refused: the PIN tries and the rate limit still apply."""
    return (fetch_site or "").lower() == "cross-site" or (origin is not None and not origin_ok(origin, host))


def wait_text(seconds: float) -> str:
    s = max(1, int(-(-seconds // 1)))
    return f"{s} seconds" if s < 120 else f"{-(-s // 60)} minutes"


def unlock_page(error: str = "") -> str:
    msg = f'<p class="err" role="alert">{escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Call Santa</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #0b0d12; color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  main {{ min-height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 0 16px; box-sizing: border-box; text-align: center; }}
  h1 {{ font-size: 30px; font-weight: 600; margin: 0 0 6px; }}
  p {{ opacity: .85; margin: 0 0 22px; }}
  form {{ display: flex; flex-direction: column; gap: 14px; width: min(260px, 100%); }}
  input {{ font-size: 28px; letter-spacing: 10px; text-align: center; padding: 12px; border-radius: 12px;
    border: 1px solid #3a3f4b; background: #1c1e26; color: #fff; }}
  button {{ font-size: 18px; padding: 12px; border-radius: 12px; border: 0; background: #2fbf57; color: #fff;
    cursor: pointer; }}
  .err {{ color: #ff8a80; opacity: 1; }}
</style>
</head>
<body>
<main>
  <h1>Call Santa</h1>
  <p>Grown-ups: enter the PIN.</p>
  {msg}
  <form method="post" action="/unlock">
    <input name="pin" type="password" inputmode="numeric" autocomplete="off" aria-label="PIN" autofocus required>
    <button type="submit">Unlock</button>
  </form>
</main>
</body>
</html>"""
