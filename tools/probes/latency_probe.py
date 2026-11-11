#!/usr/bin/env python3
"""Stage A1 latency probe (live, ai/gemma4:e4b only). Does NOT edit santa/; everything variant-specific lives here.

Replays the long_session_memory turns from evals/bench.py, REPS times per variant, and records per turn:
TTFT, stream total, wall time of the reply call, fact-extraction time, and the llama.cpp `timings`
(cache_n = prompt tokens reused from the prompt cache, prompt_n = tokens processed fresh).

  V0  current Santa.reply (extraction inside reply, per-speaker system prompt)
  V1  V0 with memory.extract_facts stubbed (no extraction call, no facts)
  V2  V1 inside reply, then the REAL extraction after reply returns (outside the timed window); next turn timed
  V3  probe-built messages: constant system prompt (all names/ages, no facts), active child's facts as a note on the
      final user message only (not stored in history), history trimmed in blocks of 4; extraction off
  V4  V3 + real extraction after each turn
  V5  diagnostic: current Santa.reply, extraction stubbed, profiles PRE-SEEDED with facts (system prompt differs
      per speaker, but no extraction call) -> isolates cause (i) from cause (ii)

All variants start with Emma, Leo and Ziv registered (as /add does before a real session), no ages, no facts
(except V5). Extra tests: identical request twice; TTFT vs prompt length (3 sizes).

Usage: PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python tools/probes/latency_probe.py [--reps 5] [--fake]
Writes tools/probes/out/latency.jsonl and tools/probes/out/latency.md.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
# never read or write the real profiles.json
os.environ["SANTA_PROFILES"] = str(Path(tempfile.mkdtemp(prefix="santa-impl-")) / "profiles.json")
sys.path.insert(0, str(ROOT))

from santa import config, memory, safety  # noqa: E402
from santa import persona  # noqa: E402
from santa.brain import Santa  # noqa: E402

_spec = importlib.util.spec_from_file_location("bench", ROOT / "evals" / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)  # patches memory.save to a no-op (fine here)
memory.save = lambda *a, **k: None

MODEL = "ai/gemma4:e4b"
SCEN = next(s for s in bench.SCENARIOS if s["id"] == "long_session_memory")
KIDS0 = {"Emma": {"facts": []}, "Leo": {"facts": []}, "Ziv": {"facts": []}}
SEED = {"Emma": {"facts": ["has a little brother named Theo", "Theo is two years old"]},
        "Leo": {"facts": ["likes trains"]},
        "Ziv": {"facts": ["has a cat named Pickles", "wants a big red truck"]}}
REAL_EXTRACT = memory.extract_facts
STUB = lambda *a, **k: []  # noqa: E731


# ------------------------------------------------------------------ recording client proxy
class Rec:
    """Wraps an OpenAI client; records every call (kind, ttft, timings, prompt chars)."""

    def __init__(self, client, log):
        self._c, self.log = client, log

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def with_options(self, **kw):
        return Rec(self._c.with_options(**kw), self.log)

    def create(self, **kw):
        msgs = kw.get("messages", [])
        rec = {"stream": bool(kw.get("stream")), "max_tokens": kw.get("max_tokens"),
               "prompt_chars": sum(len(m["content"]) for m in msgs),
               "sys_sha": hashlib.sha1(msgs[0]["content"].encode()).hexdigest()[:8] if msgs else None,
               "n_msgs": len(msgs), "t0": time.perf_counter()}
        self.log.append(rec)
        resp = self._c.chat.completions.create(**kw)
        if not kw.get("stream"):
            rec["secs"] = time.perf_counter() - rec["t0"]
            rec["timings"] = (getattr(resp, "model_extra", None) or {}).get("timings")
            return resp

        def gen():
            first = None
            for ch in resp:
                if first is None and ch.choices and ch.choices[0].delta.content:
                    first = time.perf_counter() - rec["t0"]
                    rec["ttft"] = first
                t = (getattr(ch, "model_extra", None) or {}).get("timings")
                if t:
                    rec["timings"] = t
                yield ch
            rec["secs"] = time.perf_counter() - rec["t0"]
        return gen()


def last(log, stream):
    return next((r for r in reversed(log) if r["stream"] == stream), {})


# ------------------------------------------------------------------ V3/V4: probe-built stable prompt
class StableSanta:
    """Same model call and filter as Santa.reply, but a constant system prompt and block-trimmed history."""

    def __init__(self, client, profiles):
        self.client, self.profiles, self.history, self.start = client, profiles, [], 0
        self.system = persona.SANTA_PROMPT.format(kids_block=persona.kids_block(profiles, None))

    def build(self, speaker, text):
        safe = safety.redact_private(text)
        label = f"{speaker}: {safe}" if speaker else safe
        facts = (self.profiles.get(speaker) or {}).get("facts", [])
        note = f"\n(Santa remembers about {speaker}: {'; '.join(facts[-8:])})" if facts else ""
        while len(self.history) - self.start + 1 > config.HISTORY_TURNS:
            self.start += 4  # drop whole blocks: the prefix stays identical for several turns
        window = self.history[self.start:]
        while window and window[0]["role"] != "user":
            window = window[1:]
        msgs = [{"role": "system", "content": self.system}] + window + [{"role": "user", "content": label + note}]
        return msgs, label, safe != text

    def reply(self, speaker, text):
        msgs, label, redacted = self.build(speaker, text)
        stream = self.client.chat.completions.create(model=MODEL, messages=msgs, stream=True,
                                                     temperature=config.TEMPERATURE, max_tokens=config.MAX_TOKENS,
                                                     extra_body=config.EXTRA_BODY)
        raw = "".join(ch.choices[0].delta.content or "" for ch in stream if ch.choices)
        answer, _ = safety.sanitize_ex(raw)
        self.history += [{"role": "user", "content": label}, {"role": "assistant", "content": answer}]
        return answer, raw, redacted


def extract_after(client, profiles, speaker, text, raw, redacted):
    """The same gating as Santa.reply's extraction block, but called by the probe after the reply."""
    t = time.perf_counter()
    if speaker and speaker in profiles and raw and not redacted:
        for f in REAL_EXTRACT(client, MODEL, speaker, safety.redact_private(text)):
            memory.add_fact(profiles, speaker, f)
    return time.perf_counter() - t


# ------------------------------------------------------------------ one session
def session(variant, rep, make_client):
    log = []
    rows = []
    profiles = copy.deepcopy(SEED if variant == "V5" else KIDS0)
    if variant in ("V0", "V1", "V2", "V5"):
        s = Santa(model=MODEL)
        s.client = Rec(s.client if make_client is None else make_client(), log)
        s.profiles = profiles
        assert s.warm_up(), s.last_error
        for i, tn in enumerate(SCEN["turns"]):
            memory.extract_facts = REAL_EXTRACT if variant == "V0" else STUB
            n_before = len(log)
            s.set_active(tn["s"])
            t = time.perf_counter()
            answer = s.reply(tn["s"], tn["t"])
            wall = time.perf_counter() - t
            ex = [r for r in log[n_before:] if not r["stream"] and r["max_tokens"] == 120]
            extract_s = ex[0]["secs"] if ex else None
            if variant == "V2":
                memory.extract_facts = REAL_EXTRACT
                redacted = safety.redact_private(tn["t"]) != tn["t"]
                extract_s = extract_after(s.client, s.profiles, tn["s"], tn["t"], s.last_raw, redacted)
                ex = [r for r in log[n_before:] if not r["stream"] and r["max_tokens"] == 120]
            st = last(log, True)
            rows.append(row(variant, rep, i, tn, st, ex, s.last_stats.get("ttft"), s.last_stats.get("total"),
                            wall, extract_s, s.last_raw, answer, s.profiles))
    else:
        client = Rec(Santa(model=MODEL).client if make_client is None else make_client(), log)
        client.with_options(timeout=90).chat.completions.create(  # the same warm-up request Santa.warm_up sends
            model=MODEL, messages=[{"role": "user", "content": "hi"}], max_tokens=1, temperature=0.0,
            extra_body=config.EXTRA_BODY)
        ss = StableSanta(client, profiles)
        for i, tn in enumerate(SCEN["turns"]):
            n_before = len(log)
            t = time.perf_counter()
            answer, raw, redacted = ss.reply(tn["s"], tn["t"])
            wall = time.perf_counter() - t
            st = last(log, True)
            extract_s = None
            if variant == "V4":
                extract_s = extract_after(client, profiles, tn["s"], tn["t"], raw, redacted)
            ex = [r for r in log[n_before:] if not r["stream"]]
            rows.append(row(variant, rep, i, tn, st, ex, st.get("ttft"), st.get("secs"), wall, extract_s,
                            raw, answer, profiles))
    memory.extract_facts = REAL_EXTRACT
    return rows


def row(variant, rep, i, tn, st, ex, ttft, total, wall, extract_s, raw, answer, profiles):
    tm = st.get("timings") or {}
    et = (ex[0].get("timings") or {}) if ex else {}
    return {"variant": variant, "rep": rep, "idx": i, "speaker": tn["s"], "child": tn["t"],
            "ttft": ttft, "total": total, "wall": wall, "extract_s": extract_s,
            "cache_n": tm.get("cache_n"), "prompt_n": tm.get("prompt_n"), "prompt_ms": tm.get("prompt_ms"),
            "predicted_n": tm.get("predicted_n"), "prompt_chars": st.get("prompt_chars"), "sys_sha": st.get("sys_sha"),
            "n_msgs": st.get("n_msgs"), "extract_cache_n": et.get("cache_n"), "extract_prompt_n": et.get("prompt_n"),
            "raw": raw, "answer": answer, "facts": {k: list(v.get("facts", [])) for k, v in profiles.items()}}


# ------------------------------------------------------------------ extra tests
def one_stream(client, msgs, max_tokens=8):
    t0 = time.perf_counter()
    first, timings = None, None
    for ch in client.chat.completions.create(model=MODEL, messages=msgs, stream=True, temperature=0.0,
                                             max_tokens=max_tokens, extra_body=config.EXTRA_BODY):
        if first is None and ch.choices and ch.choices[0].delta.content:
            first = time.perf_counter() - t0
        timings = (getattr(ch, "model_extra", None) or {}).get("timings") or timings
    return {"ttft": first, "secs": time.perf_counter() - t0, **{k: (timings or {}).get(k) for k in
                                                                ("cache_n", "prompt_n", "prompt_ms")}}


def base_messages(n_pairs):
    """Santa-like prompt: system prompt + n_pairs of history. A nonce first so the first request is never cached."""
    sysp = f"[session {uuid.uuid4().hex}]\n" + persona.build_system_prompt(KIDS0, None)
    msgs = [{"role": "system", "content": sysp}]
    turns = SCEN["turns"]
    for k in range(n_pairs):
        tn = turns[k % len(turns)]
        msgs += [{"role": "user", "content": f"{tn['s']}: {tn['t']}"},
                 {"role": "assistant", "content": "Ho ho ho! That sounds wonderful. My elves would love to hear "
                                                  "all about it while they make toys in the snowy workshop."}]
    msgs.append({"role": "user", "content": "Leo: can you fly"})
    return msgs


def extras(client):
    out = {"twice": [], "length": []}
    for _ in range(3):
        m = base_messages(4)
        a, b = one_stream(client, m), one_stream(client, m)
        out["twice"].append({"first": a, "second": b})
    for n_pairs in (0, 15, 40):
        for _ in range(3):
            r = one_stream(client, base_messages(n_pairs))
            r["n_pairs"] = n_pairs
            out["length"].append(r)
    return out


# ------------------------------------------------------------------ report
def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round(q / 100 * len(xs) + 0.5)) - 1))  # nearest rank
    return xs[k]


def f(x, nd=2):
    return "–" if x is None else f"{x:.{nd}f}"


def report(rows, ex, model_secs, reps):
    V = ["V0", "V1", "V2", "V3", "V4", "V5"]
    desc = {"V0": "current (extraction inside reply)", "V1": "extraction off",
            "V2": "extraction after reply, next turn timed", "V3": "stable prompt, extraction off",
            "V4": "stable prompt + extraction after turn", "V5": "diagnostic: pre-seeded facts, extraction off"}
    L = ["# A1 latency probe: long_session_memory on ai/gemma4:e4b (generated by tools/probes/latency_probe.py)\n",
         f"Reps per variant: {reps} (V5: see n). 10 turns per session. Total model time {model_secs/60:.1f} min. "
         "Percentiles are nearest-rank; with n=5, p95 = the maximum. `cache_n` = prompt tokens reused from "
         "llama.cpp's prompt cache, `prompt_n` = prompt tokens processed fresh (from the server's own `timings`).\n",
         "## Summary over turns 1-9 (turn 0 follows the warm-up request in every variant)\n",
         "| Variant | what | n | TTFT p50 | TTFT p95 | stream total p50 | p95 | reply() wall p50 | p95 | "
         "fresh prompt tokens p50 | cache hit (cache_n > 100) | extraction s p50 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for v in V:
        rs = [r for r in rows if r["variant"] == v and r["idx"] >= 1]
        if not rs:
            continue
        hit = sum(1 for r in rs if (r["cache_n"] or 0) > 100)
        L.append(f"| {v} | {desc[v]} | {len(rs)} | {f(pct([r['ttft'] for r in rs], 50))} | "
                 f"{f(pct([r['ttft'] for r in rs], 95))} | {f(pct([r['total'] for r in rs], 50))} | "
                 f"{f(pct([r['total'] for r in rs], 95))} | {f(pct([r['wall'] for r in rs], 50))} | "
                 f"{f(pct([r['wall'] for r in rs], 95))} | {f(pct([r['prompt_n'] for r in rs], 50), 0)} | "
                 f"{hit}/{len(rs)} | {f(pct([r['extract_s'] for r in rs], 50))} |")
    L += ["\n## Per turn index: TTFT p50 / p95 (s), stream total p50 / p95 (s), median fresh prompt tokens\n",
          "| turn | speaker | " + " | ".join(V) + " |", "|---|---|" + "---|" * len(V)]
    for i, tn in enumerate(SCEN["turns"]):
        cells = []
        for v in V:
            rs = [r for r in rows if r["variant"] == v and r["idx"] == i]
            cells.append("–" if not rs else
                         f"{f(pct([r['ttft'] for r in rs], 50))}/{f(pct([r['ttft'] for r in rs], 95))} · "
                         f"{f(pct([r['total'] for r in rs], 50))}/{f(pct([r['total'] for r in rs], 95))} · "
                         f"{f(pct([r['prompt_n'] for r in rs], 50), 0)}")
        L.append(f"| {i} | {tn['s']} | " + " | ".join(cells) + " |")
    L += ["\n## Extraction calls: do they reuse the Santa prompt cache? (V0, V2, V4)\n"]
    for v in ("V0", "V2", "V4"):
        rs = [r for r in rows if r["variant"] == v and r["extract_prompt_n"] is not None]
        if rs:
            L.append(f"- {v}: n={len(rs)}, extraction cache_n p50 {f(pct([r['extract_cache_n'] for r in rs], 50), 0)}, "
                     f"prompt_n p50 {f(pct([r['extract_prompt_n'] for r in rs], 50), 0)}, "
                     f"secs p50 {f(pct([r['extract_s'] for r in rs], 50))} p95 {f(pct([r['extract_s'] for r in rs], 95))}")
    L += ["\n## Identical request twice (system prompt + 4 history pairs, nonce so the first is uncached)\n",
          "| pair | 1st TTFT | 1st cache_n / prompt_n | 2nd TTFT | 2nd cache_n / prompt_n |", "|---|---|---|---|---|"]
    for k, p in enumerate(ex["twice"]):
        a, b = p["first"], p["second"]
        L.append(f"| {k} | {f(a['ttft'])} | {a['cache_n']} / {a['prompt_n']} | {f(b['ttft'])} | {b['cache_n']} / {b['prompt_n']} |")
    L += ["\n## TTFT vs prompt length (uncached)\n", "| history pairs | prompt tokens | TTFT p50 | prompt_ms p50 | tokens/s |",
          "|---|---|---|---|---|"]
    for n in (0, 15, 40):
        rs = [r for r in ex["length"] if r["n_pairs"] == n]
        toks = pct([r["prompt_n"] for r in rs], 50) or 0
        pms = pct([r["prompt_ms"] for r in rs], 50) or 0
        L.append(f"| {n} | {toks} | {f(pct([r['ttft'] for r in rs], 50))} | {f(pms, 0)} | "
                 f"{f(toks / (pms / 1000) if pms else None, 0)} |")
    sys_changes = {}
    for v in V:
        rs = sorted((r for r in rows if r["variant"] == v and r["rep"] == 0), key=lambda r: r["idx"])
        sys_changes[v] = sum(1 for a, b in zip(rs, rs[1:]) if a["sys_sha"] != b["sys_sha"])
    L += ["\n## System prompt changes between consecutive turns (rep 0)\n",
          ", ".join(f"{v}: {n}/9" for v, n in sys_changes.items())]
    (OUT / "latency.md").write_text("\n".join(L) + "\n")
    print(f"wrote {OUT / 'latency.md'}")


# ------------------------------------------------------------------ main
def fake_client_factory():
    """Offline smoke test of the probe logic: a tiny fake OpenAI client (no network)."""
    from types import SimpleNamespace as NS

    class Fake:
        def with_options(self, **kw):
            return self

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, **kw):
            tm = {"cache_n": 5, "prompt_n": 50, "prompt_ms": 10.0, "predicted_n": 3}
            if kw.get("stream"):
                def g():
                    yield NS(choices=[NS(delta=NS(content="Ho ho! Hi there."))], model_extra={})
                    yield NS(choices=[NS(delta=NS(content=None))], model_extra={"timings": tm})
                return g()
            return NS(choices=[NS(message=NS(content='{"facts": ["likes snow"]}'))], model_extra={"timings": tm})
    return Fake


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--reps-v5", type=int, default=3)
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()
    make = fake_client_factory() if a.fake else None
    if not a.fake:
        subprocess.run(["docker", "model", "unload", "--all"], capture_output=True)
        time.sleep(2)
    t_start = time.perf_counter()
    rows = []
    for rep in range(max(a.reps, a.reps_v5)):
        for v in ("V0", "V1", "V2", "V3", "V4", "V5"):
            if rep >= (a.reps_v5 if v == "V5" else a.reps):
                continue
            rs = session(v, rep, make)
            rows += rs
            print(f"rep {rep} {v}: ttft " + " ".join(f(r["ttft"]) for r in rs)
                  + f" | {time.perf_counter() - t_start:.0f}s", flush=True)
    client = make() if a.fake else Santa(model=MODEL).client
    ex = extras(client)
    model_secs = time.perf_counter() - t_start
    if not a.fake:
        subprocess.run(["docker", "model", "unload", "--all"], capture_output=True)
    name = "latency-fake" if a.fake else "latency"
    with open(OUT / f"{name}.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.write(json.dumps({"extras": ex, "model_secs": model_secs}) + "\n")
    if not a.fake:
        report(rows, ex, model_secs, a.reps)
    else:
        print("fake run ok:", len(rows), "rows;", statistics.mean(r["wall"] for r in rows))


if __name__ == "__main__":
    main()
