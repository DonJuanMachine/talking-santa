"""A macOS alert when someone may be trying to get into Santa, with the choice to stop the server.

Raised for: a PIN lockout, the rate limit tripping, or a request for an unknown host name (DNS rebinding: a website
trying to reach Santa). At most one alert per `cooldown_s`, and never two at once.

The alert defaults to "Keep Running" and closes by itself after `timeout_s`. It never stops Santa on its own:
otherwise an attacker could end a child's call just by sending a few bad requests. "Stop Santa" shuts the server down
the same way Ctrl+C does.

Nothing leaves this Mac: the alert is a local dialog (osascript), no network service.
"""
import logging
import os
import signal
import subprocess
import sys
import threading
import time

log = logging.getLogger("santa.web")

STOP, KEEP = "Stop Santa", "Keep Running"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def mac_dialog(message: str, timeout_s: int) -> str | None:
    """Show the dialog; return the button pressed, or None (timed out, closed, or not on a Mac)."""
    script = (f'display dialog "{_esc(message)}" with title "Talking Santa" '
              f'buttons {{"{STOP}", "{KEEP}"}} default button "{KEEP}" '
              f'with icon caution giving up after {int(timeout_s)}')
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                             timeout=timeout_s + 30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if "gave up:true" in out:
        return None
    for button in (STOP, KEEP):
        if f"button returned:{button}" in out:
            return button
    return None


def stop_server() -> None:
    """Same as pressing Ctrl+C in the terminal: uvicorn finishes and the process exits."""
    os.kill(os.getpid(), signal.SIGINT)


class Alerter:
    def __init__(self, enabled: bool, cooldown_s: float = 600, timeout_s: int = 300,
                 show=mac_dialog, on_stop=stop_server, clock=time.monotonic, background: bool = True):
        self.enabled = enabled and (show is not mac_dialog or sys.platform == "darwin")
        self.cooldown_s, self.timeout_s = cooldown_s, timeout_s
        self.show, self.on_stop, self.clock, self.background = show, on_stop, clock, background
        self._last: float | None = None
        self._open = False
        self._lock = threading.Lock()
        self.fired: list[str] = []

    def alert(self, reason: str) -> bool:
        """Raise an alert unless one is open or one was raised in the last cooldown_s. True if raised."""
        log.warning("security alert: %s", reason)
        if not self.enabled:
            return False
        with self._lock:
            now = self.clock()
            if self._open or (self._last is not None and now - self._last < self.cooldown_s):
                return False
            self._open, self._last = True, now
        self.fired.append(reason)
        if self.background:
            threading.Thread(target=self._ask, args=(reason,), daemon=True).start()
        else:
            self._ask(reason)
        return True

    def _ask(self, reason: str) -> None:
        try:
            msg = (f"{reason}\n\nSanta's lockouts and rate limit are already blocking it. "
                   f"Stop Santa now? (Closes by itself in {self.timeout_s // 60} minutes and keeps running.)")
            if self.show(msg, self.timeout_s) == STOP:
                log.warning("Santa stopped from the security alert")
                self.on_stop()
        finally:
            with self._lock:
                self._open = False
