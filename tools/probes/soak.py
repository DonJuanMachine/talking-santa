#!/usr/bin/env python3
"""C4 soak test (live, ai/gemma4:e4b only, one model loaded). No product code is changed.

Phase S  long_session_memory sessions back to back for SOAK_MIN minutes of wall time: a fresh Santa per session,
         warm-up with the real system prompt, extraction ON (remember() after every reply).
Phase I  idle for IDLE_S seconds (longer than config.IDLE_REWARM_SECONDS = 300 s), then RESET_SESSIONS sessions
         through the product's idle re-warm path (last_ok_time is None -> reply_stream calls warm_up itself).
Phase U  `docker model unload --all`, then RESET_SESSIONS sessions (warm-up reloads the model).

Per session: TTFT p50/p95 (turns 1-9), first-sentence p95, fresh prompt tokens p50, the server's own timings
(prompt_ms, predicted tokens/s) so client-side TTFT can be split into server compute and everything else,
and machine state after the session: llama-server RSS/CPU, Docker backend RSS, free/compressed memory, swap,
thermal notes, `docker model ps`.
Writes tools/probes/out/soak.json and soak.md.
Usage: PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python tools/probes/soak.py [soak_minutes]
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
os.environ["SANTA_PROFILES"] = str(Path(tempfile.mkdtemp(prefix="santa-soak-")) / "profiles.json")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI, Timeout  # noqa: E402

from santa import config, memory  # noqa: E402
from santa.brain import Santa  # noqa: E402
from smoke_live import Rec, pct  # noqa: E402

MODEL = "ai/gemma4:e4b"
SOAK_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
IDLE_S = config.IDLE_REWARM_SECONDS + 30
RESET_SESSIONS = 3


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception as e:      # noqa: BLE001
        return f"ERR {e}"


def machine():
    ps = sh(["ps", "-axo", "pid=,rss=,%cpu=,comm="])
    llama = [ln.split() for ln in ps.splitlines() if "llama-server" in ln]
    backend = [ln.split() for ln in ps.splitlines() if "com.docker.backend" in ln]
    vm = sh(["vm_stat"])
    page = int(re.search(r"page size of (\d+)", vm).group(1)) if "page size" in vm else 16384

    def pages(key):
        m = re.search(rf"{key}:\s+(\d+)", vm)
        return int(m.group(1)) * page / 2**30 if m else None
    swap = re.search(r"used = ([\d.]+)M", sh(["sysctl", "vm.swapusage"]))
    therm = sh(["pmset", "-g", "therm"]).strip().replace("\n", " | ")
    return {"t": time.time(),
            "llama_rss_gb": sum(int(x[1]) for x in llama) / 2**20 if llama else None,
            "llama_cpu": sum(float(x[2]) for x in llama) if llama else None,
            "llama_pids": [x[0] for x in llama],
            "backend_rss_mb": sum(int(x[1]) for x in backend) / 2**10 if backend else None,
            "free_gb": pages("Pages free"), "compressed_gb": pages("Pages occupied by compressor"),
            "swap_used_mb": float(swap.group(1)) if swap else None,
            "thermal": therm, "docker_model_ps": sh(["docker", "model", "ps"]).strip().replace("\n", " | ")}


def session(scen, phase, k, auto_rewarm=False):
    log = []
    client = Rec(OpenAI(base_url=config.BASE_URL, api_key="x", timeout=Timeout(config.REQUEST_TIMEOUT),
                        max_retries=0), log)
    s = Santa(model=MODEL, client=client, profiles={"Emma": {"facts": []}, "Leo": {"facts": []}, "Ziv": {"facts": []}})
    t0 = time.perf_counter()
    if not auto_rewarm:
        s.warm_up()
    turns = []
    for i, tn in enumerate(scen["turns"]):
        s.set_active(tn["s"])
        r = s.reply_ex(tn["s"], tn["t"])
        t1 = time.perf_counter()
        s.remember(tn["s"], tn["t"])
        tm = dict(log[-1]) if log else {}
        turns.append({"idx": i, "ttft": r.ttft, "fs": r.first_sentence_s, "total": r.total,
                      "extract_s": time.perf_counter() - t1, "fallback": r.fallback,
                      "prompt_n": tm.get("prompt_n"), "cache_n": tm.get("cache_n"), "prompt_ms": tm.get("prompt_ms"),
                      "predicted_n": tm.get("predicted_n"), "predicted_per_second": tm.get("predicted_per_second"),
                      "text": r.text})
    later = [x for x in turns if x["idx"] >= 1]
    srv = [x["prompt_ms"] / 1000 for x in later if x["prompt_ms"] is not None]
    over = [x["ttft"] - x["prompt_ms"] / 1000 for x in later if x["prompt_ms"] is not None]
    row = {"phase": phase, "k": k, "start": time.time(), "warmup_s": s.last_warmup_seconds,
           "session_s": time.perf_counter() - t0,
           "ttft_p50": pct([x["ttft"] for x in later], 50), "ttft_p95": pct([x["ttft"] for x in later], 95),
           "ttft_turn0": turns[0]["ttft"],
           "fs_p95": pct([x["fs"] for x in turns], 95), "fresh_p50": pct([x["prompt_n"] for x in later], 50),
           "server_prompt_s_p50": pct(srv, 50), "overhead_s_p50": pct(over, 50),
           "gen_tok_s_p50": pct([x["predicted_per_second"] for x in later], 50),
           "fallbacks": sum(x["fallback"] for x in turns), "turns": turns, "machine": machine()}
    print(f"{phase} {k:3d} t+{(row['start'] - T0) / 60:5.1f}m ttft p50 {row['ttft_p50']:.2f} p95 {row['ttft_p95']:.2f} "
          f"| fs p95 {row['fs_p95']:.2f} | fresh {row['fresh_p50']} | srv prompt {row['server_prompt_s_p50']:.3f}s "
          f"overhead {row['overhead_s_p50']:.3f}s | gen {row['gen_tok_s_p50']:.1f} tok/s "
          f"| llama {row['machine']['llama_rss_gb'] or 0:.2f} GB | swap {row['machine']['swap_used_mb']} MB", flush=True)
    return row


def summarize(rows):
    def grp(sel):
        return {"n": len(sel), "ttft_p50": pct([r["ttft_p50"] for r in sel], 50),
                "fs_p95": pct([r["fs_p95"] for r in sel], 50), "server_prompt_s": pct([r["server_prompt_s_p50"] for r in sel], 50),
                "overhead_s": pct([r["overhead_s_p50"] for r in sel], 50), "gen_tok_s": pct([r["gen_tok_s_p50"] for r in sel], 50),
                "fresh": pct([r["fresh_p50"] for r in sel], 50)}
    soak = [r for r in rows if r["phase"] == "S"]
    return {"soak_first3": grp(soak[:3]), "soak_last3": grp(soak[-3:]),
            "idle_rewarm": grp([r for r in rows if r["phase"] == "I"]),
            "unload_reload": grp([r for r in rows if r["phase"] == "U"])}


def fit(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    yhat = [my + b * (x - mx) for x in xs]
    ss = sum((y - my) ** 2 for y in ys)
    r2 = 1 - sum((y - h) ** 2 for y, h in zip(ys, yhat)) / ss if ss else 0.0
    return b, r2


def write(rows, meta):
    summ = summarize(rows)
    soak = [r for r in rows if r["phase"] == "S"]
    xs = [(r["start"] - T0) / 60 for r in soak]
    slopes = {k: fit(xs, [r[k] for r in soak]) for k in ("ttft_p50", "server_prompt_s_p50", "overhead_s_p50",
                                                         "gen_tok_s_p50", "fs_p95")}
    slopes_req = {k: fit(list(range(len(soak))), [r[k] for r in soak]) for k in ("ttft_p50",)}
    meta.update({"summary": summ, "slopes_per_min": slopes, "slope_per_session": slopes_req})
    (OUT / "soak.json").write_text(json.dumps({"meta": meta, "rows": rows}, indent=1, ensure_ascii=False))
    L = ["# Soak test (generated by tools/probes/soak.py)\n",
         f"Model {MODEL}. Phase S {meta['soak_min']} min of back-to-back long_session_memory sessions "
         f"(fresh Santa, warm-up, extraction on); phase I idle {IDLE_S:.0f} s then {RESET_SESSIONS} sessions via the "
         f"idle re-warm path; phase U unload all, then {RESET_SESSIONS} sessions. Total {meta['minutes']:.1f} min.\n",
         "Linear fit over phase S (per minute of wall time): " + ", ".join(
             f"{k} {b * 1000:+.1f} ms/min (R² {r2:.2f})" if k != "gen_tok_s_p50" else f"{k} {b:+.2f} tok/s/min (R² {r2:.2f})"
             for k, (b, r2) in slopes.items()) + "\n",
         "| group | sessions | TTFT p50 | first-sentence p95 | server prompt time p50 | overhead (TTFT − server prompt) p50 "
         "| gen tok/s | fresh tokens |", "|---|---|---|---|---|---|---|---|"]
    for k, g in summ.items():
        if g["n"]:
            L.append(f"| {k} | {g['n']} | {g['ttft_p50']:.2f} | {g['fs_p95']:.2f} | {g['server_prompt_s']:.3f} | "
                     f"{g['overhead_s']:.3f} | {g['gen_tok_s']:.1f} | {g['fresh']} |")
    L += ["\n| phase | # | t (min) | TTFT p50 / p95 | turn 0 | fs p95 | fresh | srv prompt s | overhead s | gen tok/s "
          "| llama RSS GB | llama CPU% | backend RSS MB | free GB | compressed GB | swap MB | fallbacks | model ps |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        m = r["machine"]
        L.append(f"| {r['phase']} | {r['k']} | {(r['start'] - T0) / 60:.1f} | {r['ttft_p50']:.2f} / {r['ttft_p95']:.2f} | "
                 f"{r['ttft_turn0']:.2f} | {r['fs_p95']:.2f} | {r['fresh_p50']} | {r['server_prompt_s_p50']:.3f} | "
                 f"{r['overhead_s_p50']:.3f} | {r['gen_tok_s_p50']:.1f} | {m['llama_rss_gb'] or 0:.2f} | "
                 f"{m['llama_cpu'] or 0:.0f} | {m['backend_rss_mb'] or 0:.0f} | {m['free_gb'] or 0:.2f} | "
                 f"{m['compressed_gb'] or 0:.2f} | {m['swap_used_mb']} | {r['fallbacks']} | {m['docker_model_ps'][-60:]} |")
    L.append("\nEvents: " + "; ".join(meta["events"]))
    L.append(f"\nThermal (pmset -g therm) at start: {meta['thermal_start']}  \nat end: {rows[-1]['machine']['thermal']}")
    (OUT / "soak.md").write_text("\n".join(L) + "\n")
    print("wrote", OUT / "soak.md")


def main():
    global T0
    spec_ = importlib.util.spec_from_file_location("bench", ROOT / "evals" / "bench.py")
    bench = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(bench)          # memory.save -> no-op in this process
    memory.extract_facts = bench.REAL_EXTRACT
    scen = next(x for x in bench.SCENARIOS if x["id"] == "long_session_memory")
    sh(["docker", "model", "unload", "--all"])
    time.sleep(2)
    T0 = time.time()
    meta = {"model": MODEL, "soak_min": SOAK_MIN, "idle_s": IDLE_S, "events": [],
            "thermal_start": sh(["pmset", "-g", "therm"]).strip().replace("\n", " | "), "machine_start": machine()}
    rows, k = [], 0
    while time.time() - T0 < SOAK_MIN * 60:
        rows.append(session(scen, "S", k))
        k += 1
    meta["events"].append(f"soak end t+{(time.time() - T0) / 60:.1f}m after {k} sessions; idle {IDLE_S:.0f}s")
    time.sleep(IDLE_S)
    meta["events"].append("after idle: docker model ps = " + sh(["docker", "model", "ps"]).strip().replace("\n", " | "))
    for j in range(RESET_SESSIONS):
        rows.append(session(scen, "I", j, auto_rewarm=True))
    sh(["docker", "model", "unload", "--all"])
    time.sleep(2)
    meta["events"].append(f"unload --all at t+{(time.time() - T0) / 60:.1f}m; docker model ps = "
                          + sh(["docker", "model", "ps"]).strip().replace("\n", " | "))
    for j in range(RESET_SESSIONS):
        rows.append(session(scen, "U", j))
    sh(["docker", "model", "unload", "--all"])
    meta["minutes"] = (time.time() - T0) / 60
    write(rows, meta)


T0 = time.time()
if __name__ == "__main__":
    main()
