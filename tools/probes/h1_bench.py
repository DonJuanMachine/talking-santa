#!/usr/bin/env python3
"""Stage H1: measure STT, TTS and the brain before building anything. No UI. Writes tools/probes/out/h_*.

    h1_bench.py stt [engine model]   STT latency + memory (each engine/model in a fresh subprocess)
    h1_bench.py tts                  Kokoro v1.0 (kokoro-onnx): time to first audio, real-time factor, memory
    h1_bench.py audition             voice audition WAVs -> tools/probes/out/voice_audition/ (Don picks by ear)
    h1_bench.py gemma_audio          does Docker Model Runner accept input_audio for ai/gemma4:e4b?
    h1_bench.py load [turns]         30 real brain turns with STT + TTS running in the same process
    h1_bench.py keepalive [trials]   TTFT after an idle gap, with and without a warm_up() ping in the gap

Synthetic audio only (tools/probes/h_synth.py, macOS `say`, adult voices). Accuracy on child speech is NOT measured.
Run with PYTHONDONTWRITEBYTECODE=1 and the Stage H venv (outside the repo).
"""
import base64
import io
import json
import os
import re
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import h_synth  # noqa: E402

MODELS = Path.home() / ".cache" / "talking-santa" / "models"
MLX_REPOS = {"base.en": "mlx-community/whisper-base.en-mlx", "small.en": "mlx-community/whisper-small.en-mlx",
             "large-v3-turbo": "mlx-community/whisper-large-v3-turbo"}
NAMES = ["Emma", "Leo", "Ziv"]
HINT = "Emma, Leo, Ziv."
SANTA_SENTENCES = [
    "Ho ho ho!",
    "Hello, little friend!",
    "A puppy sounds wonderful, Emma!",
    "I'll tell my elves all about it.",
    "Do you like to play in the snow?",
    "My reindeer love carrots, and Rudolph's nose glows so bright on snowy nights!",
]
AUDITION_LINES = [
    ("hello", "Ho ho ho! Hello, little friend!"),
    ("reply3", "Oh, a red truck sounds wonderful, Leo! I'll tell my elves all about it. "
               "Do you like to play in the snow?"),
]
AUDITION_VOICES = ["am_michael", "am_puck", "am_santa", "am_onyx", "bm_george", "bm_fable"]
AUDITION_SPEEDS = [0.85, 0.9, 1.0]


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def rss_mb() -> float:
    import psutil
    return psutil.Process().memory_info().rss / 1e6


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # bytes on macOS


def words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", t.lower().replace("’", "'"))


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def write_wav(path: Path, samples: np.ndarray, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------------------------------------------- STT
def make_stt(engine: str, model: str):
    """Returns transcribe(audio_f32_16k, hint) -> (text, info)."""
    if engine == "mlx":
        import mlx_whisper
        repo = MLX_REPOS[model]

        def run(audio, hint=HINT):
            r = mlx_whisper.transcribe(audio, path_or_hf_repo=repo, language="en", initial_prompt=hint,
                                       temperature=0.0, condition_on_previous_text=False, verbose=None)
            segs = r.get("segments", [])
            info = {"avg_logprob": min((s["avg_logprob"] for s in segs), default=None),
                    "no_speech_prob": max((s["no_speech_prob"] for s in segs), default=None)}
            return r.get("text", "").strip(), info
        return run
    if engine == "cpp":
        from pywhispercpp.model import Model
        m = Model(str(MODELS / f"ggml-{model}.bin"), print_progress=False, print_realtime=False,
                  print_timestamps=False, redirect_whispercpp_logs_to=False, language="en", no_context=True,
                  single_segment=False, temperature=0.0)

        def run(audio, hint=HINT):
            segs = m.transcribe(audio, initial_prompt=hint)
            probs = [getattr(s, "probability", None) for s in segs]
            probs = [p for p in probs if p is not None and p == p]
            return " ".join(s.text.strip() for s in segs).strip(), {"min_prob": min(probs) if probs else None}
        return run
    raise ValueError(engine)


def stt_one(engine: str, model: str) -> dict:
    """Runs in its own process."""
    clips = h_synth.clips()
    rss0 = rss_mb()
    t0 = time.perf_counter()
    run = make_stt(engine, model)
    run(np.zeros(16000, dtype=np.float32) + 1e-4)  # load + first-call compile
    load_s = time.perf_counter() - t0
    rows = []
    for c in clips:
        audio = h_synth.read_wav(c["path"])
        t = time.perf_counter()
        text, info = run(audio)
        dt = time.perf_counter() - t
        named = [n for n in NAMES if n.lower() in c["text"].lower()]
        rows.append({"id": c["id"], "voice": c["voice"], "seconds": round(c["seconds"], 2), "latency": round(dt, 3),
                     "wer": round(wer(c["text"], text), 3), "names_ok": all(re.search(rf"\b{n}\b", text, re.I)
                                                                         for n in named) if named else None,
                     "named": bool(named), "info": info, "hyp": text})
    mem = {"rss_before_mb": round(rss0, 1), "rss_after_mb": round(rss_mb(), 1), "peak_rss_mb": round(peak_rss_mb(), 1)}
    if engine == "mlx":
        import mlx.core as mx
        mem["mlx_peak_mb"] = round(mx.get_peak_memory() / 1e6, 1)
    # Latency on silence-padded clips: does the recognizer invent text on a quiet tail? (gated audio has <=0.3 s)
    return {"engine": engine, "model": model, "load_s": round(load_s, 2), "mem": mem, "rows": rows}


def bucket(sec: float) -> str:
    return "2s" if sec < 2.6 else ("5s" if sec < 7 else "10s")


def cmd_stt(argv):
    if len(argv) == 2:   # child process
        print("JSON:" + json.dumps(stt_one(*argv)))
        return
    results = []
    for engine in ("cpp", "mlx"):
        for model in ("base.en", "small.en", "large-v3-turbo"):
            print(f"STT {engine} {model} ...", flush=True)
            p = subprocess.run([sys.executable, __file__, "stt", engine, model], capture_output=True, text=True,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("JSON:")), None)
            if not line:
                results.append({"engine": engine, "model": model, "error": p.stderr[-800:]})
                print("  FAILED", p.stderr[-400:])
                continue
            results.append(json.loads(line[5:]))
    (OUT / "h_stt.json").write_text(json.dumps(results, indent=1))
    md = ["# H1 STT benchmark (synthetic adult speech from macOS `say`; NOT child speech)", "",
          f"{len(h_synth.clips())} clips: {len(h_synth.PHRASES)} phrases x {len(h_synth.VOICES)} voices "
          f"({', '.join(h_synth.VOICES)}). Name hint passed as the initial prompt: `{HINT}`. Temperature 0 only "
          "(no fallback re-decoding). Each engine/model runs in a fresh process; the first call (load + compile) "
          "is excluded from latency.", "",
          "| engine | model | load s | p50 2s | p50 5s | p50 10s | max | WER mean | names ok | peak RSS MB | MLX peak MB |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if "error" in r:
            md.append(f"| {r['engine']} | {r['model']} | FAILED | | | | | | | | |")
            continue
        by = {b: [x["latency"] for x in r["rows"] if bucket(x["seconds"]) == b] for b in ("2s", "5s", "10s")}
        named = [x for x in r["rows"] if x["named"]]
        md.append(f"| {'whisper.cpp (Metal)' if r['engine'] == 'cpp' else 'mlx-whisper'} | {r['model']} | "
                  f"{r['load_s']} | {pct(by['2s'], .5):.3f} | {pct(by['5s'], .5):.3f} | {pct(by['10s'], .5):.3f} | "
                  f"{max(x['latency'] for x in r['rows']):.3f} | "
                  f"{statistics.mean(x['wer'] for x in r['rows']):.3f} | "
                  f"{sum(bool(x['names_ok']) for x in named)}/{len(named)} | {r['mem']['peak_rss_mb']} | "
                  f"{r['mem'].get('mlx_peak_mb', '–')} |")
    md += ["", "Worst transcripts per engine/model (WER > 0.15):", ""]
    for r in results:
        for x in r.get("rows", []):
            if x["wer"] > 0.15:
                md.append(f"- {r['engine']} {r['model']} {x['id']}/{x['voice']}: WER {x['wer']} → `{x['hyp']}`")
    (OUT / "h_stt.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


# ------------------------------------------------------------------------------------------------------- TTS
def make_kokoro():
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    so = ort.SessionOptions()
    so.intra_op_num_threads = int(os.getenv("KOKORO_THREADS", "0"))   # 0 = onnxruntime default
    sess = ort.InferenceSession(str(MODELS / "kokoro-v1.0.onnx"), so, providers=["CPUExecutionProvider"])
    return Kokoro.from_session(sess, str(MODELS / "voices-v1.0.bin"))


def cmd_tts(argv):
    rss0 = rss_mb()
    t0 = time.perf_counter()
    k = make_kokoro()
    k.create("Ho ho ho!", voice="am_michael", speed=0.9, lang="en-us")
    load_s = time.perf_counter() - t0
    rss1 = rss_mb()
    rows = []
    for rep in range(3):
        for s in SANTA_SENTENCES:
            t = time.perf_counter()
            samples, sr = k.create(s, voice="am_michael", speed=0.9, lang="en-us")
            dt = time.perf_counter() - t
            dur = len(samples) / sr
            rows.append({"text": s, "words": len(s.split()), "synth_s": round(dt, 3), "audio_s": round(dur, 2),
                         "rtf": round(dt / dur, 3), "rep": rep})
    res = {"engine": "kokoro-onnx", "model": "kokoro-v1.0.onnx (fp32)", "voice": "am_michael", "speed": 0.9,
           "load_s": round(load_s, 2), "rss_before_mb": round(rss0, 1), "rss_after_load_mb": round(rss1, 1),
           "peak_rss_mb": round(peak_rss_mb(), 1), "rows": rows}
    (OUT / "h_tts.json").write_text(json.dumps(res, indent=1))
    md = ["# H1 TTS benchmark: Kokoro-82M v1.0 via kokoro-onnx (onnxruntime CPU)", "",
          f"Voice am_michael, speed 0.9. Load + first call {res['load_s']} s. RSS {res['rss_before_mb']} → "
          f"{res['rss_after_load_mb']} MB (peak {res['peak_rss_mb']} MB). 3 repetitions per sentence; the synthesis "
          "is per sentence, so time to first audio of a sentence = its synthesis time.", "",
          "| sentence | words | synth s (p50 of 3) | audio s | RTF |", "|---|---|---|---|---|"]
    for s in SANTA_SENTENCES:
        rs = [r for r in rows if r["text"] == s]
        md.append(f"| {s} | {rs[0]['words']} | {pct([r['synth_s'] for r in rs], .5):.3f} | {rs[0]['audio_s']} | "
                  f"{pct([r['rtf'] for r in rs], .5):.3f} |")
    md.append(f"\nOverall RTF p50 {pct([r['rtf'] for r in rows], .5):.3f}, max {max(r['rtf'] for r in rows):.3f}.")
    (OUT / "h_tts.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


def cmd_audition(argv):
    k = make_kokoro()
    d = OUT / "voice_audition"
    n = 0
    for v in AUDITION_VOICES:
        for sp in AUDITION_SPEEDS:
            for lid, text in AUDITION_LINES:
                samples, sr = k.create(text, voice=v, speed=sp, lang="en-us")
                write_wav(d / f"{v}_{sp:.2f}_{lid}.wav", samples, sr)
                n += 1
    (d / "README.txt").write_text(
        "Kokoro-82M v1.0 voice audition (kokoro-onnx). Files: <voice>_<speed>_<line>.wav\n"
        "Lines:\n" + "".join(f"  {lid}: {t}\n" for lid, t in AUDITION_LINES) +
        "Default in the app: am_michael at 0.9 (SANTA_VOICE / SANTA_SPEED). Pick by ear; nothing was chosen here.\n")
    print(f"wrote {n} WAVs to {d}")


# --------------------------------------------------------------------------------------------- Gemma audio
def cmd_gemma_audio(argv):
    from openai import OpenAI
    from santa import config
    c = h_synth.clips(voices=["Samantha"])
    clip = next(x for x in c if x["id"] == "s5_cat")
    buf = io.BytesIO()
    pcm = (h_synth.read_wav(clip["path"]) * 32767).astype(np.int16)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    b64 = base64.b64encode(buf.getvalue()).decode()
    client = OpenAI(base_url=config.BASE_URL, api_key="x", timeout=120, max_retries=0)
    res = {"model": config.MODEL, "endpoint": config.BASE_URL + "/chat/completions"}
    t = time.perf_counter()
    try:
        r = client.chat.completions.create(
            model=config.MODEL, max_tokens=60, temperature=0.0, extra_body=config.EXTRA_BODY,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "Transcribe this audio exactly. Reply with the words only."},
                {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}]}])
        res.update(ok=True, seconds=round(time.perf_counter() - t, 3), text=r.choices[0].message.content,
                   reference=clip["text"], wer=round(wer(clip["text"], r.choices[0].message.content or ""), 3))
    except Exception as e:
        res.update(ok=False, seconds=round(time.perf_counter() - t, 3), error=f"{type(e).__name__}: {e}"[:1500])
    if res["ok"]:   # warm runs on every clip (the first call above may include a model load)
        rows = []
        for c in h_synth.clips():
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes((h_synth.read_wav(c["path"]) * 32767).astype(np.int16).tobytes())
            t = time.perf_counter()
            r = client.chat.completions.create(
                model=config.MODEL, max_tokens=80, temperature=0.0, extra_body=config.EXTRA_BODY,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Transcribe this audio exactly. Reply with the words only."},
                    {"type": "input_audio", "input_audio": {"data": base64.b64encode(buf.getvalue()).decode(),
                                                            "format": "wav"}}]}])
            hyp = r.choices[0].message.content or ""
            named = [n for n in NAMES if n.lower() in c["text"].lower()]
            rows.append({"id": c["id"], "voice": c["voice"], "seconds": round(c["seconds"], 2),
                         "latency": round(time.perf_counter() - t, 3), "wer": round(wer(c["text"], hyp), 3),
                         "named": bool(named),
                         "names_ok": all(re.search(rf"\b{n}\b", hyp, re.I) for n in named) if named else None,
                         "hyp": hyp})
        res["warm_rows"] = rows
        by = {b: [x["latency"] for x in rows if bucket(x["seconds"]) == b] for b in ("2s", "5s", "10s")}
        named = [x for x in rows if x["named"]]
        res["summary"] = {f"p50_{b}": round(pct(v, .5), 3) for b, v in by.items()}
        res["summary"].update(wer_mean=round(statistics.mean(x["wer"] for x in rows), 3),
                              names_ok=f"{sum(bool(x['names_ok']) for x in named)}/{len(named)}",
                              max_latency=max(x["latency"] for x in rows))
    (OUT / "h_gemma_audio.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "warm_rows"}, indent=1))


# ------------------------------------------------------------------------------------- latency under load
def docker_ps() -> str:
    try:
        return subprocess.run(["docker", "model", "ps"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e:
        return f"error: {e}"


def cmd_load(argv):
    """Per turn: STT on a synthetic clip -> brain.reply_stream -> each released sentence goes straight to TTS on a
    second thread (as the app does). Also re-measures TTFT with nothing else running for comparison."""
    os.environ["SANTA_PROFILES"] = str(Path(tempfile.mkdtemp(prefix="santa-h1-")) / "profiles.json")
    from openai import OpenAI, Timeout
    from santa import config
    from santa.brain import Santa
    import queue
    engine, model = (argv[1], argv[2]) if len(argv) >= 3 else ("mlx", "small.en")
    turns = int(argv[0]) if argv else 30
    stt = make_stt(engine, model)
    stt(np.zeros(16000, dtype=np.float32) + 1e-4)
    tts = make_kokoro()
    tts.create("Ho ho ho!", voice="am_michael", speed=0.9, lang="en-us")
    client = OpenAI(base_url=config.BASE_URL, api_key="x", timeout=Timeout(config.REQUEST_TIMEOUT), max_retries=0)
    profiles = {"Emma": {"age": 4, "facts": ["has a cat named Mittens"]}, "Leo": {"age": 3, "facts": []},
                "Ziv": {"age": 4, "facts": ["has a hamster named Nibbles"]}}
    santa = Santa(client=client, profiles=profiles)
    t = time.perf_counter()
    ok = santa.warm_up()
    warm = time.perf_counter() - t
    clips = [c for c in h_synth.clips() if c["seconds"] < 7]
    speakers = ["Emma", "Leo", "Ziv"]
    rows = []
    for i in range(turns):
        if i and i % 10 == 0:    # a fresh session every 10 turns, like separate calls
            santa = Santa(client=client, profiles=profiles)
            santa.last_ok_time = time.monotonic()
        c = clips[i % len(clips)]
        audio = h_synth.read_wav(c["path"])
        t_end = time.perf_counter()
        text, _ = stt(audio, "Santa, " + HINT)
        t_stt = time.perf_counter()
        q: "queue.Queue" = queue.Queue()
        first_audio = {}

        def tts_worker():
            while True:
                s = q.get()
                if s is None:
                    return
                tts.create(s, voice="am_michael", speed=0.9, lang="en-us")
                first_audio.setdefault("t", time.perf_counter())
        th = threading.Thread(target=tts_worker)
        th.start()
        first_sent = None
        n = 0
        for s in santa.reply_stream(speakers[i % 3], text):
            first_sent = first_sent or time.perf_counter()
            n += 1
            q.put(s)
        q.put(None)
        th.join()
        r = santa.last_reply
        rows.append({"turn": i, "clip": c["id"], "hyp": text, "stt_s": round(t_stt - t_end, 3), "ttft": round(r.ttft, 3),
                     "first_sentence_s": round(r.first_sentence_s, 3),
                     "first_sentence_from_end": round(first_sent - t_end, 3),
                     "first_audio_from_end": round(first_audio["t"] - t_end, 3), "sentences": n,
                     "fallback": r.fallback, "reason": r.reason})
        print(rows[-1], flush=True)
        time.sleep(2.0)  # the child listens to Santa for a moment
    res = {"engine": engine, "model": model, "warm_up_ok": ok, "warm_up_s": round(warm, 2), "rows": rows,
           "docker_model_ps_end": docker_ps(), "peak_rss_mb": round(peak_rss_mb(), 1)}
    (OUT / "h_load.json").write_text(json.dumps(res, indent=1))
    keys = ["stt_s", "ttft", "first_sentence_s", "first_sentence_from_end", "first_audio_from_end"]
    md = [f"# H1 latency under load ({turns} real brain turns, Gemma resident, STT {engine} {model} + Kokoro in the "
          "same process)", "",
          "STT runs on the clip, then `reply_stream`; each released sentence is synthesized on a second thread while "
          "the brain continues. Times are from the endpoint decision (T_end = the moment STT starts). TTFT and first "
          "sentence are the brain's own numbers (from its request start).", "",
          "| measure | p10 | p50 | p90 | max |", "|---|---|---|---|---|"]
    for k_ in keys:
        xs = [r[k_] for r in rows]
        md.append(f"| {k_} | {pct(xs, .1):.3f} | {pct(xs, .5):.3f} | {pct(xs, .9):.3f} | {max(xs):.3f} |")
    md.append(f"\nFallbacks: {sum(r['fallback'] for r in rows)}/{turns}. Warm-up {res['warm_up_s']} s. "
              f"Peak RSS {res['peak_rss_mb']} MB.\n\n`docker model ps` at the end:\n```\n{res['docker_model_ps_end']}\n```")
    (OUT / "h_load.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


def cmd_keepalive(argv):
    """TTFT of a real turn after an idle gap of GAP s: arm A pings warm_up() every 100 s during the gap, arm B
    does not. Alternating, `trials` per arm. The model stays loaded in both arms (Docker keeps it ~5 min)."""
    os.environ["SANTA_PROFILES"] = str(Path(tempfile.mkdtemp(prefix="santa-h1-")) / "profiles.json")
    from openai import OpenAI, Timeout
    from santa import config
    from santa.brain import Santa
    trials = int(argv[0]) if argv else 3
    gap = float(argv[1]) if len(argv) > 1 else 210.0
    client = OpenAI(base_url=config.BASE_URL, api_key="x", timeout=Timeout(config.REQUEST_TIMEOUT), max_retries=0)
    profiles = {"Emma": {"age": 4, "facts": []}, "Leo": {"age": 3, "facts": []}, "Ziv": {"age": 4, "facts": []}}
    rows = []
    s = Santa(client=client, profiles=profiles)
    s.warm_up()
    for t_ in range(trials):
        for arm in ("ping", "none"):
            s.reply_ex("Emma", "hi santa")          # a turn, then idle
            t0 = time.monotonic()
            pings = 0
            while time.monotonic() - t0 < gap:
                time.sleep(5)
                if arm == "ping" and time.monotonic() - t0 >= 100 * (pings + 1):
                    s.warm_up()
                    pings += 1
            s.last_ok_time = time.monotonic()      # keep the brain's own idle re-warm out of the measurement
            fresh = Santa(client=client, profiles=profiles)
            fresh.last_ok_time = time.monotonic()
            r = fresh.reply_ex("Leo", "do reindeer like carrots?")
            rows.append({"trial": t_, "arm": arm, "gap_s": gap, "pings": pings, "ttft": round(r.ttft, 3),
                         "first_sentence_s": round(r.first_sentence_s, 3), "fallback": r.fallback,
                         "ps": docker_ps().splitlines()[-1] if docker_ps() else ""})
            print(rows[-1], flush=True)
    (OUT / "h_keepalive.json").write_text(json.dumps(rows, indent=1))
    md = [f"# Keep-alive effect on TTFT ({trials} trials per arm, idle gap {gap:.0f} s, fresh session each turn)", "",
          "| arm | TTFT values (s) | p50 | first sentence p50 |", "|---|---|---|---|"]
    for arm in ("ping", "none"):
        xs = [r["ttft"] for r in rows if r["arm"] == arm]
        fs = [r["first_sentence_s"] for r in rows if r["arm"] == arm]
        md.append(f"| {arm} | {', '.join(f'{x:.3f}' for x in xs)} | {pct(xs, .5):.3f} | {pct(fs, .5):.3f} |")
    (OUT / "h_keepalive.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    fn = globals().get(f"cmd_{cmd}")
    if not fn:
        print(__doc__)
        sys.exit(1)
    fn(sys.argv[2:])
