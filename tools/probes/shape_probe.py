#!/usr/bin/env python3
"""Stage A2 shape probe (live, ai/gemma4:e4b only). Does NOT edit santa/ or evals/.

For each persona label (v1, v3): monkeypatch santa.persona.SANTA_PROMPT in THIS process with the text of
evals/personas/persona_<label>.txt, run the 20 single-turn cases of evals/cases.json plus the 4 multi-turn
SCENARIOS of evals/bench.py, N samples each, fact extraction stubbed off, the same flow as `bench.py gen`
(new Santa per case/sample, bench.run_turn / bench._anon). Writes raw + heard (current filter) per turn to
tools/probes/out/shape-<label>.jsonl. Nothing is written to evals/results/.

  gen:    python tools/probes/shape_probe.py gen v1 v3 [--n 3]
  report: python tools/probes/shape_probe.py report v1 v3      -> tools/probes/out/shape.md

The remove-only reference filter is tools/audit/experiments/prefix_filter_prototype.py (imported, not edited).
Importing it re-runs parts of the audit at import time and would rewrite files in tools/audit/experiments/out/;
_import_prototype() points the audit's output folder at a temp dir first so tools/audit stays untouched.
"""
import argparse
import copy
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
os.environ["SANTA_PROFILES"] = str(Path(tempfile.mkdtemp(prefix="santa-impl-")) / "profiles.json")
sys.path.insert(0, str(ROOT))

from santa import memory, persona, safety  # noqa: E402
from santa.brain import Santa  # noqa: E402

MODEL = "ai/gemma4:e4b"
PERSONAS = ROOT / "evals" / "personas"


def _load_bench():
    spec = importlib.util.spec_from_file_location("bench", ROOT / "evals" / "bench.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)  # patches memory.save to a no-op (fine in this process)
    memory.save = lambda *a, **k: None
    return b


def _import_prototype():
    exp = ROOT / "tools" / "audit" / "experiments"
    sys.path.insert(0, str(exp))
    import _common  # noqa: E402
    tmp = Path(tempfile.mkdtemp(prefix="santa-impl-auditout-"))
    _common.OUT = tmp
    _common.write = lambda name, text: (tmp / name).write_text(text)
    import prefix_filter_prototype as P  # noqa: E402
    import quality as Q  # noqa: E402
    return P, Q, _common


# ------------------------------------------------------------------ generation
def gen(labels, n):
    bench = _load_bench()
    cases = json.loads((ROOT / "evals" / "cases.json").read_text())
    subprocess.run(["docker", "model", "unload", "--all"], capture_output=True)
    time.sleep(2)
    bench.memory.extract_facts = bench.STUB_EXTRACT
    memory.extract_facts = bench.STUB_EXTRACT
    t_start = time.perf_counter()
    for label in labels:
        text = (PERSONAS / f"persona_{label}.txt").read_text()
        persona.SANTA_PROMPT = text  # this process only
        rows = []
        for case in cases["cases"]:
            for k in range(n):
                s = Santa(model=MODEL)
                s.profiles = copy.deepcopy(cases["profiles"])
                sp = case["speaker"]
                r = bench.run_turn(s, sp, case["text"]) if sp else bench._anon(s, case["text"])
                rows.append({"label": label, "kind": "single", "scenario": case["id"], "sample": k, "idx": 0,
                             "speaker": sp, "child": case["text"], **r})
        print(f"[{label}] single done {time.perf_counter() - t_start:.0f}s", flush=True)
        for sc in bench.SCENARIOS:
            for k in range(n):
                s = Santa(model=MODEL)
                s.profiles = copy.deepcopy(sc["profiles"])
                for i, tn in enumerate(sc["turns"]):
                    r = bench.run_turn(s, tn["s"], tn["t"])
                    rows.append({"label": label, "kind": "multi", "scenario": sc["id"], "sample": k, "idx": i,
                                 "speaker": tn["s"], "child": tn["t"], **r})
        print(f"[{label}] multi done {time.perf_counter() - t_start:.0f}s", flush=True)
        with open(OUT / f"shape-{label}.jsonl", "w") as fh:
            for r in rows:
                r["heard"] = r.pop("answer")
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {OUT / f'shape-{label}.jsonl'} ({len(rows)} turns)", flush=True)
    subprocess.run(["docker", "model", "unload", "--all"], capture_output=True)
    print(f"model time {(time.perf_counter() - t_start) / 60:.1f} min")


# ------------------------------------------------------------------ measurement
_MARKUP = re.compile(r"[*_#`>]|^\s*(?:[-•]|\d+\.)\s|[\U0001F000-\U0001FAFF☀-➿⬀-⯿]", re.M)


def shape(raw, P, C):
    """Raw shape flags (empty list = compliant). Same counting as the reference filter: sentences of the cleaned
    text, a leading interjection opener is free."""
    S = P.S
    clean = S._clean(P._drop_standalone(raw))
    sents = [x for x in S._SENT_SPLIT.split(clean) if x.strip()]
    content = len(sents) - (1 if len(sents) > 1 and S._is_opener(sents[0]) else 0)
    f = []
    if raw.count("?") > 1:
        f.append("questions>1")
    if content > 3:
        f.append("sentences>3")
    if len(clean.split()) > 45:
        f.append("words>45")
    spans = [sp for sp in C.standalone_spans(raw) if C.W(sp)]
    stage = (any(not all(w in C.SOUNDS for w in C.W(sp)) for sp in spans)
             or any(S._is_direction(a or b) for a, b in re.findall(r"\*+([^*]+?)\*+|\(([^)]*)\)", raw))
             or any(re.fullmatch(rf"(?:{S._BARE})\W*", x, re.I) for x in S._SENT_SPLIT.split(S._clean(raw))))
    if stage:
        f.append("stage")
    if _MARKUP.search(raw):
        f.append("markup")
    if S._BLOCK_RE.search(raw) or S.looks_private(raw):
        f.append("safety")
    if not raw.strip():
        f.append("empty")
    return f


def norm(s):
    return " ".join(s.split())


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round(q / 100 * len(xs) + 0.5)) - 1))
    return xs[k]


def report(labels):
    P, Q, C = _import_prototype()
    S = P.S
    L = ["# A2 shape probe: persona v1 vs v3 on ai/gemma4:e4b (generated by tools/probes/shape_probe.py)\n",
         "Single-turn cases (evals/cases.json) + multi-turn SCENARIOS (evals/bench.py), N=3, extraction stubbed off. "
         "`today` = current santa.safety.sanitize; `remove-only` = tools/audit/experiments/prefix_filter_prototype.speak. "
         "`material` uses the audit's classifier (quality.classify: fallback, dropped, cut, demoted, lost question, "
         "lost negation). Every cell is count/denominator.\n"]
    data = {}
    for label in labels:
        rows = [json.loads(x) for x in (OUT / f"shape-{label}.jsonl").read_text().splitlines()]
        ok = [r for r in rows if r["raw"].strip() and not str(r.get("error_reason") or "").startswith(("model_error", "empty_stream"))]
        for r in ok:
            r["flags"] = shape(r["raw"], P, C)
            r["prefix"] = P.speak(r["raw"])
            r["today"] = S.sanitize(r["raw"])
            r["heard_mismatch"] = norm(r["today"]) != norm(r["heard"])  # 0 expected for fresh runs
            r["mat_today"] = bool(Q.classify(r, r["today"], S.FALLBACK) & Q.MATERIAL)
            r["mat_prefix"] = bool(Q.classify(r, r["prefix"], S.FALLBACK) & Q.MATERIAL)
            r["clean"] = S._clean(P._drop_standalone(r["raw"]))
        data[label] = (rows, ok)

    def frac(xs, pred):
        k = sum(1 for x in xs if pred(x))
        return f"{k}/{len(xs)} ({100 * k / len(xs):.1f}%)" if xs else "–"

    L += ["## Shape table\n", "| metric | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]

    def line(name, pred, sub=None):
        L.append(f"| {name} | " + " | ".join(frac(data[l][1] if sub is None else sub(data[l][1]), pred)
                                             for l in labels) + " |")
    L.append("| turns (model errors excluded) | " + " | ".join(f"{len(data[l][1])} ({len(data[l][0]) - len(data[l][1])} errors)"
                                                     for l in labels) + " |")
    line("stored heard != sanitize(raw) recomputed (sanity, expect 0)", lambda r: r["heard_mismatch"])
    line("**raw shape-compliant** (all rules)", lambda r: not r["flags"])
    for fl in ("questions>1", "sentences>3", "words>45", "stage", "markup", "safety"):
        line(f"&nbsp;&nbsp;raw breaks: {fl}", lambda r, fl=fl: fl in r["flags"])
    line("**passes remove-only filter unchanged** (heard == raw, whitespace aside)",
         lambda r: norm(r["prefix"]) == norm(r["raw"]))
    line("passes remove-only with no content change (only markup removed)", lambda r: norm(r["prefix"]) == norm(r["clean"]))
    line("intervention (material) - today's filter", lambda r: r["mat_today"])
    line("intervention (material) - remove-only", lambda r: r["mat_prefix"])
    line("text changed at all - today's filter", lambda r: norm(r["today"]) != norm(r["raw"]))
    line("text changed at all - remove-only", lambda r: norm(r["prefix"]) != norm(r["raw"]))
    line("fallback - today / remove-only", lambda r: r["today"] == S.FALLBACK or r["prefix"] == S.FALLBACK)
    line("raw: two or more '?'", lambda r: r["raw"].count("?") >= 2)
    line("raw: no '?'", lambda r: "?" not in r["raw"])
    line("heard (remove-only): two or more '?'", lambda r: r["prefix"].count("?") >= 2)
    line("heard (remove-only): no '?'", lambda r: "?" not in r["prefix"])
    line("heard (today): no '?'", lambda r: "?" not in r["today"])
    for kind in ("single", "multi"):
        line(f"raw shape-compliant, {kind}-turn only", lambda r: not r["flags"],
             sub=lambda xs, kind=kind: [x for x in xs if x["kind"] == kind])

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0

    def nsent(t):
        return len([x for x in S._SENT_SPLIT.split(S._clean(t)) if x.strip()])
    L.append("| mean words raw / heard remove-only / heard today | " + " | ".join(
        f"{mean([len(r['raw'].split()) for r in data[l][1]]):.1f} / {mean([len(r['prefix'].split()) for r in data[l][1]]):.1f}"
        f" / {mean([len(r['today'].split()) for r in data[l][1]]):.1f}" for l in labels) + " |")
    L.append("| mean sentences raw / heard remove-only | " + " | ".join(
        f"{mean([nsent(r['raw']) for r in data[l][1]]):.2f} / {mean([nsent(r['prefix']) for r in data[l][1]]):.2f}"
        for l in labels) + " |")
    L += ["\n## Latency (s), errors excluded\n",
          "| label | set | n | TTFT p50 | TTFT p95 | total p50 | total p95 |", "|---|---|---|---|---|---|---|"]
    for l in labels:
        for kind in ("single", "multi"):
            xs = [r for r in data[l][1] if r["kind"] == kind]
            L.append(f"| {l} | {kind} | {len(xs)} | {pct([r['ttft'] for r in xs], 50):.2f} | {pct([r['ttft'] for r in xs], 95):.2f}"
                     f" | {pct([r['total'] for r in xs], 50):.2f} | {pct([r['total'] for r in xs], 95):.2f} |")
    L.append("\n## Shape failures per scenario (raw not compliant)\n")
    for l in labels:
        bad = {}
        for r in data[l][1]:
            if r["flags"]:
                bad.setdefault(r["scenario"], []).append(",".join(r["flags"]))
        L.append(f"- **{l}**: " + "; ".join(f"{k} {len(v)}x ({', '.join(sorted(set(v)))})" for k, v in sorted(bad.items())))
    L.append("\n## Every reply the remove-only filter changes (raw -> heard)\n")
    for l in labels:
        L.append(f"### {l}\n")
        for r in data[l][1]:
            if norm(r["prefix"]) != norm(r["raw"]):
                L.append(f"- [{r['scenario']} s{r['sample']} i{r['idx']}] child: {r['child']!r}\n  - raw:   {r['raw']!r}\n"
                         f"  - heard: {r['prefix']!r}\n  - today: {r['today']!r}")
        L.append("")
    L.append("## 20 random raw replies per label (seed 20261105), verbatim\n")
    for l in labels:
        rnd = random.Random(20261105)
        L.append(f"### {l}\n")
        for k, r in enumerate(rnd.sample(data[l][1], 20), 1):
            L.append(f"{k}. [{r['scenario']} s{r['sample']} i{r['idx']}] **{r['speaker']}:** {r['child']}\n"
                     f"   > {r['raw']}\n   flags: {r['flags'] or 'none'}")
        L.append("")
    (OUT / "shape.md").write_text("\n".join(L) + "\n")
    print(f"wrote {OUT / 'shape.md'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "report"])
    ap.add_argument("labels", nargs="+")
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    gen(a.labels, a.n) if a.cmd == "gen" else report(a.labels)


if __name__ == "__main__":
    main()
