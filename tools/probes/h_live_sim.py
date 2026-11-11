#!/usr/bin/env python3
"""Stage H3 live simulation: the real app (real STT, TTS, VAD and ai/gemma4:e4b) driven over its WebSocket by a fake
browser that streams synthetic speech in real time and "plays" Santa's audio by waiting for its duration.

    h_live_sim.py sim  [--tag NAME]            >= 20 turns over 3 calls (Emma, Leo, Ziv) + Hang up in every state
    h_live_sim.py soak [--minutes 30]          back-to-back simulated calls; memory, docker model ps, disk check

Writes tools/probes/out/h_<tag>.json and .md. The server runs with HF_HUB_OFFLINE=1, a temporary profiles file (never
the real profiles.json), and no --debug-audio. Synthetic adult speech only (macOS `say`), NOT child speech.
"""
import argparse
import asyncio
import json
import os
import random
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
import psutil  # noqa: E402
import websockets  # noqa: E402

import h_synth  # noqa: E402

FRAME = 512
FRAME_S = FRAME / 16000
CHILDREN = {"Emma": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": []}, "Ziv": {"age": 4, "facts": []}}
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".webm", ".flac", ".m4a", ".aiff", ".aif", ".pcm", ".raw", ".opus", ".npy"}


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def docker_ps() -> str:
    try:
        return subprocess.run(["docker", "model", "ps"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e:
        return f"error: {e}"


# ------------------------------------------------------------------------------------------------ server
class Server:
    def __init__(self, metrics_file: Path, extra_env=None):
        self.port = free_port()
        self.tmp = Path(tempfile.mkdtemp(prefix="santa-h-sim-"))
        self.profiles = self.tmp / "profiles.json"
        self.profiles.write_text(json.dumps({"children": CHILDREN}, indent=2))
        self.metrics_file = metrics_file
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
               "SANTA_PROFILES": str(self.profiles), **(extra_env or {})}
        self.log = open(self.tmp / "server.log", "w")
        self.p = subprocess.Popen([sys.executable, "-m", "santa.web", "--port", str(self.port), "--metrics-file",
                                   str(metrics_file)], cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.proc = psutil.Process(self.p.pid)
        self.peak_rss = 0

    def wait_ready(self, timeout=180):
        import urllib.request
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.p.poll() is not None:
                raise RuntimeError("server died: " + (self.tmp / "server.log").read_text()[-2000:])
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/status", timeout=2).read()
                return time.time() - t0
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("server not ready")

    def status(self) -> dict:
        import urllib.request
        return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/status", timeout=5).read())

    def sample(self) -> float:
        try:
            rss = self.proc.memory_info().rss / 1e6
            for c in self.proc.children(recursive=True):
                rss += c.memory_info().rss / 1e6
        except psutil.Error:
            return 0.0
        self.peak_rss = max(self.peak_rss, rss)
        return rss

    def connections(self) -> list[str]:
        out = subprocess.run(["lsof", "-nP", "-a", "-i", "-p", str(self.p.pid)], capture_output=True, text=True).stdout
        return [ln for ln in out.splitlines()[1:]]

    def stop(self):
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGINT)
            try:
                self.p.wait(15)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.log.close()


# ------------------------------------------------------------------------------------------------ fake browser
class Browser:
    def __init__(self, ws):
        self.ws = ws
        self.state = None
        self.active = None
        self.mic: list[np.ndarray] = []         # queued audio to "speak" (16 kHz float32)
        self.events: list[tuple[float, dict]] = []
        self.utt: dict[int, dict] = {}
        self.metrics: list[dict] = []
        self.state_ev = asyncio.Event()
        self.audio_after_stop = 0
        self.stop_at = None
        self.dead_below = 0
        self.closed = False

    async def send(self, m):
        await self.ws.send(json.dumps(m))

    async def reader(self):
        try:
            async for msg in self.ws:
                now = time.monotonic()
                if isinstance(msg, bytes):
                    uid = int.from_bytes(msg[:4], "little")
                    if uid < self.dead_below:
                        self.audio_after_stop += 1
                        continue
                    u = self.utt.setdefault(uid, {"samples": 0, "start": None, "ended": False})
                    if u["start"] is None:
                        u["start"] = now + 0.03          # a browser starts ~30 ms after scheduling
                        asyncio.get_running_loop().call_later(0.03, lambda i=uid: asyncio.ensure_future(
                            self.send({"type": "playback_started", "id": i})))
                    u["samples"] += (len(msg) - 4) // 2
                    continue
                m = json.loads(msg)
                self.events.append((now, m))
                t = m["type"]
                if t == "state":
                    self.state, self.active = m["state"], m["active"]
                    self.state_ev.set()
                elif t == "audio_start":
                    self.utt.setdefault(m["id"], {"samples": 0, "start": None, "ended": False})
                elif t == "audio_end":
                    u = self.utt.get(m["id"])
                    if u is not None and u["start"] is not None:
                        end = u["start"] + u["samples"] / 24000
                        asyncio.get_running_loop().call_later(max(0.0, end - now) + 0.02, lambda i=m["id"]: (
                            asyncio.ensure_future(self.send({"type": "playback_ended", "id": i}))))
                elif t == "stop_audio":
                    self.stop_at = now
                    self.dead_below = max([self.dead_below] + [k + 1 for k in self.utt])
                    self.utt.clear()
                elif t == "metrics":
                    self.metrics.append(m)
        except websockets.ConnectionClosed:
            pass
        self.closed = True

    async def mic_loop(self):
        """Real-time mic: one 512-sample frame every 32 ms; quiet noise when nothing is queued."""
        t0 = time.monotonic()
        k = 0
        buf = np.zeros(0, dtype=np.float32)
        rng = np.random.default_rng(1)
        while not self.closed:
            if len(buf) < FRAME and self.mic:
                buf = np.concatenate([buf, self.mic.pop(0)])
            if len(buf) >= FRAME:
                frame, buf = buf[:FRAME], buf[FRAME:]
            else:
                frame = (rng.standard_normal(FRAME) * 0.002).astype(np.float32)
            if self.state not in (None, "IDLE"):
                await self.ws.send((np.clip(frame, -1, 1) * 32767).astype("<i2").tobytes())
            k += 1
            await asyncio.sleep(max(0.0, t0 + k * FRAME_S - time.monotonic()))

    def mic_busy(self) -> bool:
        return bool(self.mic)

    async def wait_state(self, *states, timeout=30.0):
        t0 = time.monotonic()
        while self.state not in states:
            self.state_ev.clear()
            left = timeout - (time.monotonic() - t0)
            if left <= 0:
                raise TimeoutError(f"state {self.state}, wanted {states}")
            try:
                await asyncio.wait_for(self.state_ev.wait(), left)
            except asyncio.TimeoutError:
                raise TimeoutError(f"state {self.state}, wanted {states}")


def clip_audio(c) -> np.ndarray:
    return h_synth.read_wav(c["path"])


async def one_turn(b: Browser, audio: np.ndarray, timeout=40.0) -> dict | None:
    """Speak, then wait for Santa to answer and finish. Returns the server's metrics for the turn."""
    n0 = len(b.metrics)
    await b.wait_state("LISTENING")
    await asyncio.sleep(0.45)                       # echo guard (300 ms) + a little
    b.mic.append(audio)
    t0 = time.monotonic()
    while len(b.metrics) == n0:
        if time.monotonic() - t0 > timeout:
            raise TimeoutError("no metrics for turn")
        await asyncio.sleep(0.05)
    await b.wait_state("LISTENING", "IDLE", "HANGUP")
    return b.metrics[-1]


async def hangup(b: Browser) -> dict:
    t = time.monotonic()
    b.stop_at = None
    await b.send({"type": "hangup"})
    while b.stop_at is None:
        await asyncio.sleep(0.002)
        if time.monotonic() - t > 3:
            break
    stop = (b.stop_at - t) if b.stop_at else None
    await b.wait_state("IDLE", timeout=15)
    return {"stop_s": stop, "idle_s": time.monotonic() - t}


# ------------------------------------------------------------------------------------------------ scenarios
def turn_plan():
    """3 calls x 7 turns. The child is identified by voice ("I'm Emma"), by the adult strip, or by name."""
    clips = {(c["id"], c["voice"]): c for c in h_synth.clips()}
    common = ["t_cookies", "t_elves", "t_sled", "s5_snow", "t_thanks", "s2_puppy"]
    return [
        ("Emma", "voice", ["s2_hi_emma"] + common, "Samantha"),
        ("Leo", "button", ["s5_leo_truck"] + common[::-1], "Daniel"),
        ("Ziv", "voice", ["s2_max", "t_hamster", "t_what_cat"] + common[:4], "Karen"),
    ], clips


async def run_sim(url: str, srv: Server) -> dict:
    plan, clips = turn_plan()
    res = {"turns": [], "calls": [], "hangups": []}
    async with websockets.connect(url, max_size=None) as ws:
        b = Browser(ws)
        rd, mic = asyncio.ensure_future(b.reader()), asyncio.ensure_future(b.mic_loop())
        await b.wait_state("IDLE")
        for child, how, ids, voice in plan:
            await b.send({"type": "call"})
            await b.wait_state("RINGING")
            await b.wait_state("LISTENING", timeout=30)
            call = {"child": child, "how": how, "active_at_call": b.active, "turns": 0}
            if how == "button":
                await b.send({"type": "set_child", "name": child})
            for cid in ids:
                m = await one_turn(b, clip_audio(clips[(cid, voice)]))
                m = dict(m, child=child, clip=cid, active_after=b.active)
                res["turns"].append(m)
                call["turns"] += 1
                srv.sample()
                print(f"  {child} {cid:13s} proc {m.get('first_played_from_end')}  total {m.get('total_from_last')}"
                      f"  ext {m.get('extended')} again {m.get('say_again', False)}", flush=True)
            call["active_end"] = b.active
            call["hangup"] = await hangup(b)
            res["calls"].append(call)
        # Hang up in every live state
        for target in ("RINGING", "GREETING", "LISTENING", "THINKING", "SPEAKING"):
            await b.send({"type": "call"})
            if target in ("RINGING", "GREETING"):
                await b.wait_state(target, timeout=30)
                await asyncio.sleep(0.3)
            else:
                await b.wait_state("LISTENING", timeout=30)
                if target != "LISTENING":
                    await asyncio.sleep(0.45)
                    b.mic.append(clip_audio(clips[("s5_cat", "Samantha")]))
                    await b.wait_state(target, timeout=30)
                    if target == "SPEAKING":
                        await asyncio.sleep(0.2)
            seen = b.state
            h = await hangup(b)
            h.update(target=target, seen=seen)
            res["hangups"].append(h)
            print(f"  hangup in {seen}: stop {h['stop_s']:.3f}s idle {h['idle_s']:.2f}s", flush=True)
            await asyncio.sleep(1.0)
        # Soak finding: Forget last right before Hang up (fact extraction still running on the brain thread)
        for _ in range(3):
            await b.send({"type": "call"})
            await b.wait_state("LISTENING", timeout=30)
            await b.send({"type": "set_child", "name": "Emma"})
            await one_turn(b, clip_audio(clips[("t_hamster", "Samantha")]))
            await b.send({"type": "forget_last"})
            h = await hangup(b)
            h.update(target="FORGET+HANGUP", seen="LISTENING after Forget last")
            res["hangups"].append(h)
            print(f"  hangup right after Forget last: stop {h['stop_s']:.3f}s idle {h['idle_s']:.2f}s", flush=True)
            await asyncio.sleep(1.0)
        res["audio_after_stop"] = b.audio_after_stop
        rd.cancel()
        mic.cancel()
    return res


async def run_soak(url: str, srv: Server, minutes: float) -> dict:
    plan, clips = turn_plan()
    all_ids = sorted({c["id"] for c in h_synth.clips()})
    voices = h_synth.VOICES
    rng = random.Random(7)
    res = {"turns": [], "calls": 0, "hangups": [], "samples": [], "errors": []}
    t_end = time.monotonic() + minutes * 60
    last_sample = 0.0
    async with websockets.connect(url, max_size=None) as ws:
        b = Browser(ws)
        rd, mic = asyncio.ensure_future(b.reader()), asyncio.ensure_future(b.mic_loop())
        await b.wait_state("IDLE")
        while time.monotonic() < t_end:
            try:
                await b.send({"type": "call"})
                await b.wait_state("LISTENING", timeout=30)
                res["calls"] += 1
                child = rng.choice(list(CHILDREN))
                if rng.random() < 0.5:
                    await b.send({"type": "set_child", "name": child})
                for _ in range(rng.randint(3, 8)):
                    if time.monotonic() >= t_end:
                        break
                    cid, voice = rng.choice(all_ids), rng.choice(voices)
                    m = await one_turn(b, clip_audio(clips[(cid, voice)]))
                    res["turns"].append(dict(m, clip=cid))
                    if time.monotonic() - last_sample > 60:
                        last_sample = time.monotonic()
                        res["samples"].append({"t": round(minutes * 60 - (t_end - time.monotonic())),
                                               "rss_mb": round(srv.sample(), 1), "docker_ps": docker_ps()})
                        print(f"  t={res['samples'][-1]['t']}s rss {res['samples'][-1]['rss_mb']} MB turns "
                              f"{len(res['turns'])}", flush=True)
                    else:
                        srv.sample()
                if rng.random() < 0.15 and b.state == "LISTENING":   # sometimes the forget button
                    await b.send({"type": "forget_last"})
                res["hangups"].append(await hangup(b))
                await asyncio.sleep(rng.uniform(0.5, 3))
            except Exception as e:
                res["errors"].append(f"{type(e).__name__}: {e}")
                print("  ERROR", res["errors"][-1], flush=True)
                if len(res["errors"]) > 5:
                    break
                try:
                    await hangup(b)
                except Exception:
                    pass
        res["audio_after_stop"] = b.audio_after_stop
        rd.cancel()
        mic.cancel()
    return res


# ------------------------------------------------------------------------------------------------ disk check
SCAN = [ROOT, Path.home() / ".cache" / "talking-santa", Path(tempfile.gettempdir()),
        Path("/private/tmp"), Path.home() / "Library" / "Caches"]


def disk_listing() -> dict:
    out = {}
    for base in SCAN:
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in (".git", ".snapshots", ".venv", "node_modules")]
            for f in filenames:
                p = os.path.join(dirpath, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out[p] = (st.st_size, st.st_mtime)
    return out


def disk_diff(before: dict, after: dict, phrases: list[str], allow: list[str]) -> dict:
    new = [p for p in after if p not in before]
    changed = [p for p in after if p in before and after[p] != before[p]]
    audio = [p for p in new + changed if Path(p).suffix.lower() in AUDIO_EXT and not any(a in p for a in allow)]
    text_hits = []
    rx = re.compile("|".join(re.escape(x) for x in phrases), re.I)
    for p in new + changed:
        if any(a in p for a in allow) or after[p][0] > 20_000_000:
            continue
        try:
            data = open(p, "rb").read().decode("utf-8", "ignore")
        except OSError:
            continue
        if rx.search(data):
            text_hits.append(p)
    return {"new": len(new), "changed": len(changed), "audio_files": audio, "transcript_hits": text_hits,
            "new_sample": sorted(new)[:40]}


# ------------------------------------------------------------------------------------------------ report
def summarize(turns: list[dict]) -> list[str]:
    keys = [("stt_done_from_end", "STT done"), ("first_token_from_end", "first LLM token"),
            ("first_sentence_from_end", "first sentence released by the gate"),
            ("first_tts_from_end", "first TTS chunk"), ("first_played_from_end", "first sample played (processing)"),
            ("endpoint_wait", "endpoint wait (T_end - T_last)"),
            ("total_from_last", "total (T_last -> first sample played)"), ("spoken_s", "spoken reply duration")]
    md = ["| measure | n | p10 | p50 | p90 | max |", "|---|---|---|---|---|---|"]
    for k, label in keys:
        xs = [t[k] for t in turns if t.get(k) is not None]
        if xs:
            md.append(f"| {label} | {len(xs)} | {pct(xs, .1):.3f} | {pct(xs, .5):.3f} | {pct(xs, .9):.3f} | "
                      f"{max(xs):.3f} |")
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sim", "soak"])
    ap.add_argument("--tag", default=None)
    ap.add_argument("--minutes", type=float, default=30)
    a = ap.parse_args()
    tag = a.tag or a.mode
    OUT.mkdir(exist_ok=True)
    mfile = Path(tempfile.mkdtemp(prefix="santa-h-metrics-")) / "metrics.jsonl"
    before = disk_listing() if a.mode == "soak" else None
    t_disk0 = time.time()
    srv = Server(mfile)
    res = {"mode": a.mode, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        res["ready_s"] = round(srv.wait_ready(), 1)
        res["docker_ps_start"] = docker_ps()
        url = f"ws://127.0.0.1:{srv.port}/ws"
        t0 = time.monotonic()
        if a.mode == "sim":
            res.update(asyncio.run(run_sim(url, srv)))
        else:
            res.update(asyncio.run(run_soak(url, srv, a.minutes)))
        res["wall_s"] = round(time.monotonic() - t0, 1)
        res["connections"] = srv.connections()
        res["status_end"] = srv.status()
        res["docker_ps_end"] = docker_ps()
        res["server_alive"] = srv.p.poll() is None
    finally:
        res["peak_rss_mb"] = round(srv.peak_rss, 1)
        srv.stop()
        log_text = (srv.tmp / "server.log").read_text()
        res["server_log_tail"] = log_text[-3000:]
    if a.mode == "soak":
        after = disk_listing()
        phrases = ["Mittens", "Nibbles", "sprinkles", "puppy please", "reindeer like snow", "big red truck",
                   "ride on your sleigh", "How many elves"]
        allow = [str(srv.profiles.parent), str(mfile.parent), "/talking-santa/synth/", "/tools/probes/out/h_",
                 "/santa/web/.cache/"]
        res["disk"] = disk_diff(before, after, phrases, allow)
        res["disk"]["scanned"] = [str(p) for p in SCAN]
        res["disk"]["seconds"] = round(time.time() - t_disk0)
        res["profiles_after"] = json.loads(srv.profiles.read_text())
        docker_logs = Path.home() / "Library" / "Containers" / "com.docker.docker" / "Data" / "log"
        hits = []
        if docker_logs.exists():
            rx = re.compile("|".join(re.escape(x) for x in phrases), re.I)
            for p in docker_logs.rglob("*"):
                try:
                    if p.is_file() and p.stat().st_mtime >= t_disk0 and rx.search(
                            p.read_bytes().decode("utf-8", "ignore")):
                        hits.append(str(p))
                except OSError:
                    pass
        res["docker_log_transcript_hits"] = hits
    (OUT / f"h_{tag}.json").write_text(json.dumps(res, indent=1, default=str))
    turns = res.get("turns", [])
    md = [f"# Stage H live {a.mode} ({tag})", "",
          f"Real app over its WebSocket, real models, HF_HUB_OFFLINE=1, temp profiles. Synthetic adult speech "
          f"(macOS `say`), not child speech. Turns: {len(turns)}. Wall time {res.get('wall_s')} s. Server peak RSS "
          f"{res['peak_rss_mb']} MB (Python process; Gemma runs in Docker's llama-server).", ""]
    md += summarize([t for t in turns if not t.get("say_again")])
    sa = [t for t in turns if t.get("say_again")]
    md += ["", f"Say-again turns: {len(sa)} ({', '.join(str(t.get('stt_why')) for t in sa)}). "
               f"Extend-once fired: {sum(bool(t.get('extended')) for t in turns)}/{len(turns)} turns. "
               f"Fallbacks: {sum(bool(t.get('fallback')) for t in turns)}."]
    if res.get("hangups"):
        md += ["", "| hang up | stop_audio after (s) | idle after (s) |", "|---|---|---|"]
        for h in res["hangups"][:12]:
            md.append(f"| {h.get('seen', '')} | {h['stop_s']:.3f} | {h['idle_s']:.2f} |")
    md += ["", f"Audio chunks received after stop_audio for a stopped utterance: {res.get('audio_after_stop')}",
           f"Server tripwire hits / TTS lines: see status_end in the JSON: {res.get('status_end')}"]
    (OUT / f"h_{tag}.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
