"""FastAPI app: the call page, one WebSocket per page, and the idle keep-alive (section 4.9).

WebSocket protocol (JSON text messages + binary audio):
  browser -> server  {"type": "hello"} | {"type": "call"} | {"type": "hangup"} | {"type": "set_child", "name": str|null}
                     | {"type": "forget_last"} | {"type": "playback_started", "id": n} | {"type": "playback_ended", "id": n}
                     binary: int16 little-endian PCM, 16 kHz mono (the AudioWorklet resamples)
  server -> browser  {"type": "state", "state", "active", "children"} | ring_start | ring_stop | stop_audio
                     | {"type": "audio_start", "id", "sr"} + binary (uint32 id + int16 PCM at sr) + {"type": "audio_end", "id"}
                     | {"type": "metrics", ...numbers} | {"type": "forgot", "child", "count"}
                     | {"type": "busy"} (another page is already on a call: one call at a time)
                     | {"type": "tick"} (every settings.tick_s during a call, never while idle: the page's liveness
                       signal; app.js resets to IDLE after liveness.js LOST_MS without any message)
                     | {"type": "slow"} (once per turn: no first sentence after settings.slow_s; sent in THINKING,
                       after the canned "hold" line when one plays; the page shows "taking a while" until the next
                       state that is not THINKING) | {"type": "slow", "where": "ring"} (the ring's warm-up was still
                       running when the greeting started)
  close code 4401: this device has not entered the PIN (the page reloads to the PIN screen)
  close code 1013: too many call pages are open (MAX_SESSIONS); the page retries a little later
"""
import asyncio
import json
import logging
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from . import canned
from .access import COOKIE, Gate, origin_ok, unlock_page, wait_text
from .alerts import Alerter
from .session import MAX_AUDIO_MSG, CallSession, State, Workers
from .settings import PKG, Settings, is_loopback

log = logging.getLogger("santa.web")
STATIC = PKG / "static"


class Engines:
    """Everything loaded once per app. Tests pass fakes for any of these."""

    def __init__(self, settings: Settings, brain=None, stt=None, tts=None, vad_factory=None):
        self.s = settings
        self.brain, self.stt, self.tts, self.vad_factory = brain, stt, tts, vad_factory
        self.workers = Workers()
        self.canned_audio: dict = {}
        self.sessions: set[CallSession] = set()
        self.keepalive = {"pings": 0, "ok": 0, "last": None}
        self.totals: dict[str, int] = {}               # counters of closed sessions (numbers only)
        self.hangups: list[dict] = []

    def load(self) -> None:
        t0 = time.perf_counter()
        if self.brain is None:
            from .brain_adapter import SantaBrain
            self.brain = SantaBrain()
        if self.stt is None:
            from .stt import MlxWhisperSTT
            self.stt = MlxWhisperSTT(self.s)
            self.workers.stt.submit(self.stt.warm).result()       # compile on the STT thread
        if self.tts is None:
            from .tts import KokoroTTS, PocketTTS
            if self.s.tts_engine not in ("kokoro", "pocket"):
                raise ValueError(f"SANTA_TTS must be kokoro or pocket, not {self.s.tts_engine!r}")
            self.tts = PocketTTS(self.s) if self.s.tts_engine == "pocket" else KokoroTTS(self.s)
        if self.vad_factory is None:
            from .vad import SileroVAD
            self.vad_factory = lambda: SileroVAD(self.s.vad_model)
        self.canned_audio = self.workers.tts.submit(canned.render_all, self.tts, self.s.canned_dir).result()
        log.warning("models ready in %.1f s", time.perf_counter() - t0)

    def any_call_active(self) -> bool:
        return any(x.state != State.IDLE for x in self.sessions)

    async def keepalive_loop(self) -> None:
        """warm_up() every keepalive_s while no call is active (PHASE2_NOTES §5)."""
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(min(5.0, max(0.02, self.s.keepalive_s / 4)))
            if self.any_call_active():
                continue
            last = self.brain.last_ok_time
            if last is not None and time.monotonic() - last < self.s.keepalive_s:
                continue
            self.keepalive["pings"] += 1
            ok = await loop.run_in_executor(self.workers.brain, self.brain.warm_up)
            self.keepalive["ok"] += int(bool(ok))
            self.keepalive["last"] = time.time()


MAX_UNLOCK_BODY = 1000         # bytes; the PIN form is about 10
MAX_SESSIONS = 4               # open call pages at once (each loads its own voice-activity model)


async def _read_capped(request: Request, limit: int) -> str | None:
    """The request body as text, or None if it is longer than `limit` (stops reading at once)."""
    if int(request.headers.get("content-length") or 0) > limit:
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "replace")


UNKNOWN_HOST_ALERT = ("A request used a name this server does not answer to. A website may be trying to reach "
                      "Santa (DNS rebinding). It was refused.")


def create_app(settings: Settings | None = None, alerter: Alerter | None = None, **engines) -> FastAPI:
    s = settings or Settings()
    alerter = alerter or Alerter(enabled=s.alerts)
    eng = Engines(s, **engines)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.get_running_loop().run_in_executor(None, eng.load)
        ka = asyncio.ensure_future(eng.keepalive_loop()) if s.keepalive_s > 0 else None
        yield
        if ka:
            ka.cancel()
        eng.workers.shutdown()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engines = eng
    gate = Gate(s, on_alert=alerter.alert)
    app.state.gate = gate
    app.state.alerter = alerter

    @app.middleware("http")
    async def access(request: Request, call_next):
        r = await _access(request, call_next)
        # no framing by other sites (clickjacking), no MIME sniffing, no referrer leaks
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["Referrer-Policy"] = "no-referrer"
        return r

    async def _access(request: Request, call_next):
        if not gate.host_ok(request.headers.get("host")):
            alerter.alert(UNKNOWN_HOST_ALERT)
            return HTMLResponse("unknown host", status_code=400)  # DNS rebinding: another site's name for us
        client = request.client.host if request.client else None
        path = request.url.path
        if path == "/status" and s.network and not is_loopback(client):
            return HTMLResponse("not found", status_code=404)     # children's names: this Mac only
        if not gate.allowed(client, request.cookies):
            if not gate.admit():                                  # devices without the PIN: limited per minute
                return HTMLResponse(unlock_page("Too many tries right now. Wait a minute, then try again."),
                                    status_code=429, headers={"Retry-After": "60"})
            if path == "/":
                return HTMLResponse(unlock_page())
            if path != "/unlock":
                return HTMLResponse("locked", status_code=401)
        return await call_next(request)

    @app.post("/unlock")
    async def unlock(request: Request):
        if not gate.pin_required:
            return RedirectResponse("/", status_code=303)
        client = request.client.host if request.client else ""
        token = None
        if not gate.locked_for(client):
            body = await _read_capped(request, MAX_UNLOCK_BODY)
            if body is None:
                return HTMLResponse(unlock_page("That PIN is not right."), status_code=413)
            token = gate.try_pin(client, parse_qs(body).get("pin", [""])[0])
        if token is None:
            wait = gate.locked_for(client)
            if wait:
                return HTMLResponse(unlock_page(f"Too many tries. Wait {wait_text(wait)}."), status_code=429,
                                    headers={"Retry-After": str(math.ceil(wait))})
            return HTMLResponse(unlock_page("That PIN is not right."), status_code=401)
        r = RedirectResponse("/", status_code=303)
        r.set_cookie(COOKIE, token, max_age=30 * 86400, httponly=True, samesite="strict",
                     secure=s.cert_file is not None)
        return r

    @app.get("/")
    async def index():
        return HTMLResponse((STATIC / "index.html").read_text())

    @app.get("/static/{name}")
    async def static(name: str):
        p = (STATIC / name).resolve()
        if p.parent != STATIC.resolve() or not p.is_file():
            return HTMLResponse("not found", status_code=404)
        return FileResponse(p)

    @app.get("/santa-image")
    async def santa_image():
        # your picture in local/ (gitignored), else the older static/santa.jpg spot, else the drawn Santa
        legacy = STATIC / "santa.jpg"
        pic = s.santa_image or (legacy if legacy.is_file() else STATIC / "santa.svg")
        return FileResponse(pic, headers={"Cache-Control": "no-cache"})

    @app.get("/status")
    async def status():
        from . import safe
        totals = dict(eng.totals)
        for x in eng.sessions:
            for k, v in x.counters.items():
                totals[k] = totals.get(k, 0) + v
        return {"sessions": [x.state.value for x in eng.sessions], "keepalive": eng.keepalive,
                "children": eng.brain.names() if eng.brain else [], "counters": totals,
                "tripwire_hits": safe.tripwire_hits,
                "hangup_stop_s_max": max([h["stop_s"] for h in eng.hangups] +
                                         [h["stop_s"] for x in eng.sessions for h in x.hangup_marks], default=None)}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        host = sock.headers.get("host")
        if not (gate.host_ok(host) and origin_ok(sock.headers.get("origin"), host)):
            if not gate.host_ok(host):
                alerter.alert(UNKNOWN_HOST_ALERT)
            await sock.close(code=1008)                     # another website or rebinding: refuse the handshake
            return
        if not gate.allowed(sock.client.host if sock.client else None, sock.cookies):
            gate.admit()                                    # counts toward the per-minute limit
            await sock.accept()
            await sock.close(code=4401)                     # page reloads and shows the PIN screen
            return
        if len(eng.sessions) >= MAX_SESSIONS:
            await sock.accept()
            await sock.close(code=1013)                     # too many open call pages: try again later
            return
        await sock.accept()
        vad = await asyncio.get_running_loop().run_in_executor(None, eng.vad_factory)   # model load off the loop
        sess = CallSession(brain=eng.brain, stt=eng.stt, tts=eng.tts, vad=vad, settings=s,
                           send_json=lambda m: sock.send_text(json.dumps(m)), send_bytes=sock.send_bytes,
                           workers=eng.workers, canned_audio=eng.canned_audio)
        eng.sessions.add(sess)
        try:
            await sess.set_state(State.IDLE)
            while True:
                msg = await sock.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    if len(msg["bytes"]) > MAX_AUDIO_MSG:   # page sends 1 KiB; a huge frame would block the loop
                        sess.counters["frames_dropped_big"] = sess.counters.get("frames_dropped_big", 0) + 1
                        continue
                    await sess.audio_in(msg["bytes"])
                elif msg.get("text") is not None:
                    try:
                        data = json.loads(msg["text"])
                    except ValueError:
                        continue
                    if isinstance(data, dict):
                        if data.get("type") == "call" and any(       # one call at a time, every mode
                                x is not sess and x.state != State.IDLE for x in eng.sessions):
                            await sock.send_text(json.dumps({"type": "busy"}))   # one call at a time
                            continue
                        await sess.handle(data)
        except WebSocketDisconnect:
            pass
        finally:
            await sess.close()
            eng.sessions.discard(sess)
            for k, v in sess.counters.items():
                eng.totals[k] = eng.totals.get(k, 0) + v
            eng.hangups = (eng.hangups + sess.hangup_marks)[-200:]   # numbers only; keep the latest

    return app
