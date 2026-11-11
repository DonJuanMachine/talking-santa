"""Run Santa's call page:  python -m santa.web [--port 8765] [--network] [--debug-audio] [--metrics-file PATH]

By default binds to 127.0.0.1: open http://127.0.0.1:8765 in Chrome or Safari on this Mac.
--network: other devices on the home Wi-Fi can call too, over HTTPS (mkcert files in local/certs/) and only after
entering the PIN (SANTA_PIN, usually set in local/santa.env). See README > "Use on your home network".
"""
import argparse
import logging
import os
import sys
import socket
import subprocess
from pathlib import Path

sys.dont_write_bytecode = True

from santa import local  # noqa: E402

CERTS = local.CERTS_DIR                                               # gitignored (local/certs)


def _lan_names() -> list[str]:
    """Best effort: this Mac's Bonjour name (name.local) and Wi-Fi address, for the startup message."""
    out = []
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=2)
        if name.returncode == 0 and name.stdout.strip():
            out.append(f"{name.stdout.strip()}.local")
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
            u.connect(("192.0.2.1", 9))          # no packet is sent; this only picks the outgoing interface
            out.append(u.getsockname()[0])
    except OSError:
        pass
    return out


def main(argv=None) -> None:
    local.load_env()      # local/santa.env (e.g. SANTA_PIN) before any setting is read
    from santa import persona
    persona.use_world(local.santa_world())   # local/santa_world.txt, if you wrote one
    ap = argparse.ArgumentParser(prog="python -m santa.web")
    ap.add_argument("--port", type=int, default=int(os.getenv("SANTA_PORT", "8765")))
    ap.add_argument("--debug-audio", action="store_true",
                    help="write each child utterance to santa/web/debug_audio/ (gitignored). Off by default.")
    ap.add_argument("--metrics-file", type=Path, default=None, help="append per-turn timings (numbers only)")
    ap.add_argument("--verbose", action="store_true", help="log per-turn timings to the console")
    ap.add_argument("--network", action="store_true",
                    help="let other devices on the home network call (HTTPS + PIN from SANTA_PIN)")
    ap.add_argument("--cert", type=Path, default=CERTS / "santa.pem", help="HTTPS certificate for --network")
    ap.add_argument("--key", type=Path, default=CERTS / "santa-key.pem", help="HTTPS private key for --network")
    a = ap.parse_args(argv)

    net = {}
    if a.network:
        pin = os.getenv("SANTA_PIN", "").strip()
        if len(pin) < 6:
            sys.exit("--network needs a PIN of at least 6 characters: set SANTA_PIN=... in "
                     f"{local.ENV_FILE} (see README).")
        missing = [str(p) for p in (a.cert, a.key) if not p.is_file()]
        if missing:
            sys.exit("--network needs an HTTPS certificate. Missing: " + ", ".join(missing) +
                     "\nMake one with mkcert (see README > \"Use on your home network\").")
        lan = tuple(n.lower() for n in _lan_names())     # system.local + Wi-Fi address: the names devices use
        net = dict(host="0.0.0.0", pin=pin, cert_file=a.cert, key_file=a.key,
                   allowed_hosts=("127.0.0.1", "localhost", "::1", *lan))

    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(asctime)s %(message)s")
    import uvicorn

    from .server import create_app
    from .settings import Settings

    alerts = os.getenv("SANTA_ALERTS", "1").strip().lower() not in ("0", "false", "no", "off", "")
    s = Settings(port=a.port, debug_audio=a.debug_audio, metrics_file=a.metrics_file, alerts=alerts, **net)
    if s.debug_audio:
        logging.getLogger("santa.web").warning("DEBUG AUDIO ON: utterances are written to %s", s.debug_audio_dir)
    if s.network:
        lan = [h for h in s.allowed_hosts if h not in ("127.0.0.1", "localhost", "::1")]
        urls = "  ".join(f"https://{n}:{s.port}" for n in lan) or f"https://<this Mac>:{s.port}"
        print(f"Santa is starting on the home network (PIN required, one call at a time)... then open {urls}",
              flush=True)
    else:
        print(f"Santa is starting... then open http://{s.host}:{s.port}", flush=True)
    tls = dict(ssl_certfile=str(s.cert_file), ssl_keyfile=str(s.key_file)) if s.cert_file else {}
    # proxy_headers=False: never let an X-Forwarded-For header change who the client is (the PIN check uses it)
    uvicorn.run(create_app(s), host=s.host, port=s.port, access_log=False, log_level="warning",
                ws="websockets-sansio", ws_max_size=64 * 1024, proxy_headers=False, **tls)


if __name__ == "__main__":
    main()
