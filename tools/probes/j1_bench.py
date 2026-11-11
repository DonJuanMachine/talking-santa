#!/usr/bin/env python3
"""Stage J1: TTS speed and memory, Kokoro v1.0 vs Kyutai Pocket TTS. Writes tools/probes/out/j1_bench.{json,md}.

    j1_bench.py run                         orchestrator: checks Gemma is resident, warms it, runs every cell in a
                                            clean child process (network blocked with sandbox-exec), writes reports
    j1_bench.py cell <engine> <voice> <speed>   one cell (child process; printed as JSON)

Each cell: load (model + voice + first call), 3 warm-up rounds, then n = 10 timed runs per sentence, round-robin.
Kokoro: time to first audio = one create() call for the sentence (what santa/web/tts.py does today).
Pocket: whole-sentence time (same meaning as Kokoro) and time to the first streamed chunk (generate_audio_stream).
Run with PYTHONDONTWRITEBYTECODE=1 and nothing else loading the Mac. Gemma must be loaded (docker model).
"""
import json
import os
import resource
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MODELS = Path.home() / ".cache" / "talking-santa" / "models"
VENV = {"kokoro": Path.home() / ".venvs/talking-santa-h/bin/python",
        "pocket": Path.home() / ".venvs/talking-santa-j/bin/python"}
SENTENCES = {   # same sentences for both engines
    "L1": "Ho ho ho! Hello, little friend!",
    "5w": "A puppy sounds wonderful, Emma!",
    "L2": "Oh, a kitty named Mittens! I love kitties. What color is she?",
    "13w": "My reindeer love carrots, and Rudolph's nose glows so bright on snowy nights!",
}
N = 10
WARM = 3
CELLS = [   # (engine, voice, speed, why)
    ("kokoro", "am_michael", 0.9, "baseline: the app's current setting"),
    ("kokoro", "am_michael", 1.0, "cheapest Kokoro setting auditioned: the voice does not change the compute (same "
                                  "model, a different style vector); speed 1.0 makes the fewest output frames"),
    ("pocket", "peter_yearsley", 0.0, "shortest stored voice prompt (3.6 MB state)"),
    ("pocket", "anna", 0.0, "longest stored voice prompt (7.6 MB state)"),
]
GEMMA_URL = os.getenv("SANTA_BASE_URL", "http://localhost:12434/engines/v1") + "/chat/completions"
GEMMA_MODEL = os.getenv("SANTA_MODEL", "ai/gemma4:e4b")
SANDBOX = "(version 1)(allow default)(deny network*)"


def pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def stats(xs):
    return {"p50": round(pct(xs, .5), 3), "p90": round(pct(xs, .9), 3), "max": round(max(xs), 3), "n": len(xs)}


def rss_mb():
    import psutil
    return psutil.Process().memory_info().rss / 1e6


def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6   # bytes on macOS


# ------------------------------------------------------------------------------------------------- one cell
def cell(engine, voice, speed):
    speed = float(speed)
    rss0 = rss_mb()
    t0 = time.perf_counter()
    if engine == "kokoro":
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        sess = ort.InferenceSession(str(MODELS / "kokoro-v1.0.onnx"), ort.SessionOptions(),
                                    providers=["CPUExecutionProvider"])
        k = Kokoro.from_session(sess, str(MODELS / "voices-v1.0.bin"))
        sr = 24000

        def run(text):
            t = time.perf_counter()
            s, _ = k.create(text, voice=voice, speed=speed, lang="en-us")
            dt = time.perf_counter() - t
            return dt, None, len(s) / sr
        run("Ho ho ho!")
        threads = "onnxruntime default"
    else:
        import torch
        from pocket_tts import TTSModel
        model = TTSModel.load_model()
        state = model.get_state_for_audio_prompt(voice)
        sr = model.sample_rate

        def run(text):
            t = time.perf_counter()
            first, n = None, 0
            for chunk in model.generate_audio_stream(state, text):
                first = first or time.perf_counter() - t
                n += chunk.shape[-1]
            return time.perf_counter() - t, first, n / sr
        run("Ho ho ho!")
        threads = f"torch {torch.get_num_threads()} threads"
    load_s = time.perf_counter() - t0
    rss_load = rss_mb()
    for _ in range(WARM):
        for s in SENTENCES.values():
            run(s)
    rows = []
    for rep in range(N):
        for sid, s in SENTENCES.items():
            full, first, audio = run(s)
            rows.append({"sentence": sid, "rep": rep, "full_s": round(full, 4),
                         "first_chunk_s": round(first, 4) if first is not None else None,
                         "audio_s": round(audio, 3), "rtf": round(full / audio, 4)})
    out = {"engine": engine, "voice": voice, "speed": speed if engine == "kokoro" else None, "threads": threads,
           "load_s": round(load_s, 3), "rss_before_mb": round(rss0, 1), "rss_after_load_mb": round(rss_load, 1),
           "peak_rss_mb": round(peak_rss_mb(), 1), "rows": rows}
    return {**out, **summarize(rows, engine)}


def summarize(rows, engine):
    out = {"ttfa": {sid: stats([r["full_s"] for r in rows if r["sentence"] == sid]) for sid in SENTENCES},
           "audio_s": {sid: stats([r["audio_s"] for r in rows if r["sentence"] == sid]) for sid in SENTENCES},
           "rtf_p50": round(pct([r["rtf"] for r in rows], .5), 3), "rtf_max": round(max(r["rtf"] for r in rows), 3)}
    if engine == "pocket":
        out["first_chunk"] = {sid: stats([r["first_chunk_s"] for r in rows if r["sentence"] == sid])
                              for sid in SENTENCES}
    return out


# ---------------------------------------------------------------------------------------------- orchestrator
def docker_ps():
    try:
        return subprocess.run(["docker", "model", "ps"], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:
        return f"error: {e}"


def warm_gemma():
    body = json.dumps({"model": GEMMA_MODEL, "max_tokens": 8, "temperature": 0,
                       "messages": [{"role": "user", "content": "Say hi."}]}).encode()
    req = urllib.request.Request(GEMMA_URL, data=body, headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        r.read()
    return round(time.perf_counter() - t, 2)


def load_avg():
    return [round(x, 2) for x in os.getloadavg()]


def top_cpu(k=4):
    try:
        lines = subprocess.run(["ps", "-Ao", "%cpu,comm", "-r"], capture_output=True, text=True).stdout.splitlines()
        return [f"{ln.split(None, 1)[0]}% {Path(ln.split(None, 1)[1]).name}" for ln in lines[1:k + 1]]
    except Exception as e:
        return [f"error: {e}"]


def cmd_run(argv):
    """Two passes, the second in reverse order, so drift in background load hits both engines alike. Each cell's
    numbers are pooled over both passes (n = 2 x N per sentence); the per-pass L2 medians are kept to show drift."""
    passes = int(argv[0]) if argv else 2
    order = [CELLS[0], CELLS[2], CELLS[1], CELLS[3]]
    res = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "n_per_pass": N, "passes": passes, "warm_rounds": WARM,
           "sentences": SENTENCES, "runs": [], "cells": []}
    for pi in range(passes):
        for engine, voice, speed, why in (order if pi % 2 == 0 else order[::-1]):
            w1 = warm_gemma()
            w2 = warm_gemma()
            ps = docker_ps()
            assert "gemma4" in ps, ps
            la, top = load_avg(), top_cpu()
            print(f"pass {pi + 1} {engine} {voice} {speed}: gemma warm {w1}/{w2} s, load avg {la}, top {top}",
                  flush=True)
            p = subprocess.run(["sandbox-exec", "-p", SANDBOX, str(VENV[engine]), __file__, "cell", engine, voice,
                                str(speed)], capture_output=True, text=True,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1"})
            line = next((ln for ln in p.stdout.splitlines() if ln.startswith("JSON:")), None)
            if not line:
                raise SystemExit(f"cell failed: {p.stderr[-2000:]}")
            c = json.loads(line[5:])
            c.update(pass_no=pi + 1, why=why, gemma_warm_s=[w1, w2], gemma_ps_before=ps.splitlines()[-1],
                     load_avg_before=la, top_cpu_before=top, gemma_ps_after=docker_ps().splitlines()[-1],
                     load_avg_after=load_avg(),
                     label=f"Kokoro {voice} @ {speed}" if engine == "kokoro" else f"Pocket {voice}")
            res["runs"].append(c)
            print(f"  L2 p50 {c['ttfa']['L2']['p50']} s, RTF {c['rtf_p50']}, peak RSS {c['peak_rss_mb']} MB; "
                  f"gemma after: {c['gemma_ps_after']}", flush=True)
    for engine, voice, speed, why in CELLS:
        runs = [r for r in res["runs"] if r["engine"] == engine and r["voice"] == voice
                and (engine != "kokoro" or r["speed"] == speed)]
        rows = [row for r in runs for row in r["rows"]]
        res["cells"].append({"engine": engine, "voice": voice, "speed": runs[0]["speed"], "label": runs[0]["label"],
                             "why": why, "threads": runs[0]["threads"], "load_s": [r["load_s"] for r in runs],
                             "rss_before_mb": runs[0]["rss_before_mb"],
                             "rss_after_load_mb": [r["rss_after_load_mb"] for r in runs],
                             "peak_rss_mb": max(r["peak_rss_mb"] for r in runs),
                             "l2_p50_per_pass": [r["ttfa"]["L2"]["p50"] for r in runs], **summarize(rows, engine)})
    res["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (OUT / "j1_bench.json").write_text(json.dumps(res, indent=1))
    write_md(res)


def write_md(res):
    base = next(c for c in res["cells"] if c["engine"] == "kokoro" and c["speed"] == 0.9)
    bl2 = base["ttfa"]["L2"]["p50"]
    sids = list(res["sentences"])
    md = ["# J1 TTS speed and memory: Kokoro v1.0 vs Kyutai Pocket TTS", "",
          f"Run {res['started']} → {res['finished']}. Apple M5 (4 performance + 6 efficiency cores), 32 GB. Each "
          f"cell in a clean process (network blocked with sandbox-exec, HF_HUB_OFFLINE=1), {res['warm_rounds']} "
          f"warm-up rounds, then n = {res['n_per_pass']} per sentence, round-robin. {res['passes']} passes, the "
          "second in reverse order; the tables pool both passes "
          f"(n = {res['passes'] * res['n_per_pass']} per cell and sentence). Gemma (`ai/gemma4:e4b`) loaded and "
          "warmed with a short request before each cell (resident, idle while timing).", "",
          "Sentences: " + "; ".join(f"**{k}** \"{v}\" ({len(v.split())} words)" for k, v in res["sentences"].items()),
          "", "## Time to first audio (whole sentence), seconds: p50 / p90 / max", "",
          "For Kokoro this is one `create()` call, as the app does today. For Pocket it is the full sentence through "
          "the streaming generator, so it means the same thing.", "",
          "| cell | " + " | ".join(sids) + " | RTF p50 (max) |", "|---|" + "---|" * len(sids) + "---|"]
    for c in res["cells"]:
        md.append(f"| {c['label']} | " + " | ".join(
            f"{c['ttfa'][s]['p50']:.3f} / {c['ttfa'][s]['p90']:.3f} / {c['ttfa'][s]['max']:.3f}" for s in sids)
            + f" | {c['rtf_p50']:.3f} ({c['rtf_max']:.3f}) |")
    md += ["", "## Pocket TTS: time to the first streamed chunk, seconds: p50 / p90 / max", "",
           "| cell | " + " | ".join(sids) + " |", "|---|" + "---|" * len(sids)]
    for c in res["cells"]:
        if c.get("first_chunk"):
            md.append(f"| {c['label']} | " + " | ".join(
                f"{c['first_chunk'][s]['p50']:.3f} / {c['first_chunk'][s]['p90']:.3f} / "
                f"{c['first_chunk'][s]['max']:.3f}" for s in sids) + " |")
    md += ["", "## Load and memory", "", "| cell | why this cell | threads | load s (model + voice + first call) | "
           "RSS before → after load MB | peak RSS MB | audio s for L2 (p50) |", "|---|---|---|---|---|---|---|"]
    for c in res["cells"]:
        md.append(f"| {c['label']} | {c['why']} | {c['threads']} | {' / '.join(f'{x:.2f}' for x in c['load_s'])} | "
                  f"{c['rss_before_mb']} → {' / '.join(str(x) for x in c['rss_after_load_mb'])} | {c['peak_rss_mb']} | {c['audio_s']['L2']['p50']:.2f} |")
    md += ["", "## J2 pass bar (informational)", "",
           f"Bar: median time to first audio for L2 no more than 0.25 s above the Kokoro am_michael 0.9 baseline "
           f"measured here ({bl2:.3f} s), so ≤ {bl2 + 0.25:.3f} s.", "",
           "| cell | L2 whole sentence p50 | pass? | L2 first chunk p50 | pass if streamed? |", "|---|---|---|---|---|"]
    for c in res["cells"]:
        w = c["ttfa"]["L2"]["p50"]
        fc = c.get("first_chunk", {}).get("L2", {}).get("p50")
        md.append(f"| {c['label']} | {w:.3f} | {'yes' if w <= bl2 + 0.25 else 'no'} | "
                  f"{f'{fc:.3f}' if fc is not None else '–'} | "
                  f"{('yes' if fc <= bl2 + 0.25 else 'no') if fc is not None else '–'} |")
    md += ["", "## Drift between passes: L2 whole-sentence p50 per pass (s)", ""]
    for c in res["cells"]:
        md.append(f"- {c['label']}: " + " / ".join(f"{x:.3f}" for x in c["l2_p50_per_pass"]))
    md += ["", "## Per run: Gemma state (`docker model ps`, last line), load average, top CPU users before the cell",
           ""]
    for r in res["runs"]:
        md.append(f"- pass {r['pass_no']} {r['label']}: Gemma warm-up requests {r['gemma_warm_s']} s; "
                  f"`{r['gemma_ps_before']}` → `{r['gemma_ps_after']}`; load avg {r['load_avg_before']} → "
                  f"{r['load_avg_after']}; top: {', '.join(r['top_cpu_before'])}")
    (OUT / "j1_bench.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "cell":
        print("JSON:" + json.dumps(cell(*sys.argv[2:5])))
    elif len(sys.argv) >= 2 and sys.argv[1] == "run":
        cmd_run(sys.argv[2:])
    else:
        print(__doc__)
        sys.exit(1)
