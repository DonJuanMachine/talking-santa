#!/usr/bin/env python3
"""Facts-note layouts, live (ai/gemma4:e4b only). Stage C2 version.

long_session_memory, REPS sessions per layout, persona v1 UNCHANGED, extraction via remember() after each reply,
warm-up with the real system prompt before each session. The layouts are run interleaved (rep 0: A B B2 B3,
rep 1: B B2 B3 A, ...) so that a slow drift of the server over the run hits every layout equally.

  A   shipped note           "(Santa remembers about Ziv: has a cat named Pickles; ...)"   (santa.persona.facts_note)
  B   note_probe.md B        "(Santa already knows this about Ziv: has a cat named Pickles; ....)"
  B2  the child's notebook   "(Ziv's notebook: I have a cat named Pickles; I want a big red truck.)"
  B3  B + one instruction    "(Santa already knows this about Ziv: ... . Use this if Ziv asks what you remember.)"

Every layout keeps the system prompt constant and puts the note on the CURRENT user turn only (never in history):
the subclasses only replace the text of the last message that Santa.build_messages() built.

Recall is scored STRICTLY (C1): the reply names the fact AND does not say it doesn't know / asks to be told.
Writes tools/probes/out/note_probe2_C2.md and .json (the Stage B outputs note_probe2.md/.json are left as they were).

Usage:
  PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python tools/probes/note_probe2.py             # live run, all layouts
  PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python tools/probes/note_probe2.py --rescore   # re-score Stage B's json
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
os.environ["SANTA_PROFILES"] = str(Path(tempfile.mkdtemp(prefix="santa-note2-")) / "profiles.json")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from santa import config, memory, persona  # noqa: E402
from santa.brain import Santa  # noqa: E402
from smoke_live import Rec, dont_know, pct, strict_recall  # noqa: E402

MODEL = "ai/gemma4:e4b"
REPS = 10
GATE = {"strict_min": 18, "dont_know_max": 1, "ttft_p50_max": 0.6, "fs_p95_max": 1.5}

# Third-person verb -> first person, for B2 only. Anything else gets "my " in front ("favorite color is purple").
_FIRST = {"has": "have", "wants": "want", "likes": "like", "loves": "love", "wishes": "wish", "is": "am",
          "was": "was", "lives": "live", "plays": "play", "goes": "go", "does": "do", "doesn't": "don't",
          "enjoys": "enjoy", "hates": "hate", "misses": "miss", "gets": "get", "can": "can", "feels": "feel",
          "thinks": "think", "knows": "know", "wanted": "wanted", "had": "had", "got": "got", "saw": "saw"}


def first_person(name: str, fact: str) -> str:
    f = " ".join(str(fact).split())
    low = f.lower()
    n = name.lower()
    if low.startswith(n + "'s ") or low.startswith(n + "’s "):
        return "my " + f[len(n) + 3:]
    if low.startswith(n + " "):
        f = f[len(n) + 1:]
        low = f.lower()
    if low.startswith(("i ", "my ")):
        return f
    head, _, rest = f.partition(" ")
    if head.lower() in _FIRST:
        return "I " + _FIRST[head.lower()] + (" " + rest if rest else "")
    return "my " + f


def _facts(santa, speaker):
    facts = (santa.profiles.get(speaker) or {}).get("facts", []) if speaker else []
    return [persona._one_line(f) for f in facts[-persona.NOTE_MAX_FACTS:] if str(f).strip()]


def _with_note(build):
    """Subclass factory: keep Santa.build_messages exactly, replace only the note on the current user turn."""
    class Layout(Santa):
        def build_messages(self, speaker, text):
            msgs, label, red = super().build_messages(speaker, text)
            facts = _facts(self, speaker)
            note = build(persona._one_line(speaker), facts) if facts else ""
            msgs[-1] = {"role": "user", "content": label + note}
            return msgs, label, red
    return Layout


def note_B(name, facts):
    return f"\n(Santa already knows this about {name}: {'; '.join(facts)}.)"


def note_B2(name, facts):
    return f"\n({name}'s notebook: {'; '.join(first_person(name, f) for f in facts)}.)"


def note_B3(name, facts):
    return f"\n(Santa already knows this about {name}: {'; '.join(facts)}. Use this if {name} asks what you remember.)"


LAYOUTS = {"A": Santa, "B": _with_note(note_B), "B2": _with_note(note_B2), "B3": _with_note(note_B3)}
EXAMPLE = {"A": persona.facts_note("Ziv", ["has a cat named Pickles", "wants a big red truck"]),
           "B": note_B("Ziv", ["has a cat named Pickles", "wants a big red truck"]),
           "B2": note_B2("Ziv", ["has a cat named Pickles", "wants a big red truck"]),
           "B3": note_B3("Ziv", ["has a cat named Pickles", "wants a big red truck"])}


def score(rows, reps):
    t8 = [x for x in rows if x["idx"] == 8]
    t9 = [x for x in rows if x["idx"] == 9]
    later = [x for x in rows if x["idx"] >= 1]
    r = {
        "n_recall": len(t8) + len(t9),
        "strict": sum(strict_recall(x["text"], "pickles") for x in t8) + sum(strict_recall(x["text"], "theo") for x in t9),
        "loose": sum("pickles" in x["text"].lower() for x in t8) + sum("theo" in x["text"].lower() for x in t9),
        "pickles_strict": sum(strict_recall(x["text"], "pickles") for x in t8),
        "theo_strict": sum(strict_recall(x["text"], "theo") for x in t9),
        "pickles_in_facts": sum(any("pickles" in f.lower() for f in x["max_facts"]) for x in t8),
        "theo_in_facts": sum(any("theo" in f.lower() for f in x["emma_facts"]) for x in t9),
        "dont_know": sum(dont_know(x["text"]) for x in t8 + t9),
        "ttft_p50": pct([x["ttft"] for x in later], 50), "ttft_p95": pct([x["ttft"] for x in later], 95),
        "fs_p95_1_9": pct([x["fs"] for x in later], 95), "fs_p95_all": pct([x["fs"] for x in rows], 95),
        "fresh_p50": pct([x["prompt_n"] for x in later], 50),
        "ttft_by_turn": [round(pct([x["ttft"] for x in rows if x["idx"] == i], 50), 2) for i in range(10)],
        "ttft_p50_by_rep": [round(pct([x["ttft"] for x in later if x["rep"] == k], 50), 2) for k in range(reps)],
        "fallbacks": sum(1 for x in rows if x.get("fallback")),
        "samples": [{"idx": x["idx"], "text": x["text"], "strict": strict_recall(x["text"], "pickles" if x["idx"] == 8
                                                                                   else "theo"),
                     "facts": x["max_facts"] if x["idx"] == 8 else x["emma_facts"]} for x in t8 + t9],
    }
    fs = max(r["fs_p95_1_9"], r["fs_p95_all"])
    r["gate"] = {"strict": r["strict"] >= GATE["strict_min"], "dont_know": r["dont_know"] <= GATE["dont_know_max"],
                 "ttft_p50": r["ttft_p50"] <= GATE["ttft_p50_max"], "fs_p95": fs <= GATE["fs_p95_max"]}
    r["pass"] = all(r["gate"].values())
    return r


def main(only=None):
    from openai import OpenAI, Timeout
    spec_ = importlib.util.spec_from_file_location("bench", ROOT / "evals" / "bench.py")
    bench = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(bench)          # memory.save -> no-op in this process
    memory.extract_facts = bench.REAL_EXTRACT
    scen = next(x for x in bench.SCENARIOS if x["id"] == "long_session_memory")
    names = only or list(LAYOUTS)
    subprocess.run(["docker", "model", "unload", "--all"], capture_output=True)
    time.sleep(2)
    t_all = time.perf_counter()
    rows = {k: [] for k in names}
    for rep in range(REPS):
        order = names[rep % len(names):] + names[:rep % len(names)]
        for name in order:
            log = []
            client = Rec(OpenAI(base_url=config.BASE_URL, api_key="x", timeout=Timeout(config.REQUEST_TIMEOUT),
                                max_retries=0), log)
            s = LAYOUTS[name](model=MODEL, client=client,
                              profiles={"Emma": {"facts": []}, "Leo": {"facts": []}, "Ziv": {"facts": []}})
            s.warm_up()
            for i, tn in enumerate(scen["turns"]):
                s.set_active(tn["s"])
                r = s.reply_ex(tn["s"], tn["t"])
                s.remember(tn["s"], tn["t"])
                rows[name].append({"rep": rep, "idx": i, "text": r.text, "ttft": r.ttft, "fs": r.first_sentence_s,
                                   "fallback": r.fallback, "cache_n": log[-1].get("cache_n"),
                                   "prompt_n": log[-1].get("prompt_n"),
                                   "max_facts": list(s.profiles["Ziv"]["facts"]),
                                   "emma_facts": list(s.profiles["Emma"]["facts"])})
            last = rows[name][-10:]
            print(f"rep {rep} {name:2}: ttft p50 {pct([x['ttft'] for x in last[1:]], 50):.2f} | "
                  f"Pickles {strict_recall(last[8]['text'], 'pickles')} Theo {strict_recall(last[9]['text'], 'theo')} "
                  f"| dk {dont_know(last[8]['text']) + dont_know(last[9]['text'])}", flush=True)
    subprocess.run(["docker", "model", "unload", "--all"], capture_output=True)
    minutes = (time.perf_counter() - t_all) / 60
    res = {k: score(v, REPS) for k, v in rows.items()}
    write(res, minutes)
    (OUT / "note_probe2_C2_rows.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return res


def write(res, minutes):
    L = ["# Facts-note layouts, Stage C2 (generated by tools/probes/note_probe2.py)\n",
         f"long_session_memory, {REPS} sessions per layout (interleaved), persona v1 unchanged, extraction via remember(), "
         f"trim 8, warm-up per session. Model time {minutes:.1f} min. Recall is STRICT (names the fact and does not "
         "say it doesn't know).\n",
         f"Gate: strict recall >= {GATE['strict_min']}/20, \"don't know\" <= {GATE['dont_know_max']}/20, "
         f"TTFT p50 <= {GATE['ttft_p50_max']} s, first-sentence p95 <= {GATE['fs_p95_max']} s.\n",
         "| layout | strict recall (of 20) | Pickles / Theo strict | loose recall | facts extracted (Pickles / Theo) "
         "| \"don't know\" (of 20) | TTFT p50 / p95 turns 1-9 | first sentence p95 turns 1-9 / all | fresh tokens p50 "
         "| fallbacks | gate |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in res.items():
        failed = [k for k, v in r["gate"].items() if not v]
        L.append(f"| {name} | {r['strict']} | {r['pickles_strict']} / {r['theo_strict']} | {r['loose']} | "
                 f"{r['pickles_in_facts']} / {r['theo_in_facts']} | {r['dont_know']} | "
                 f"{r['ttft_p50']:.2f} / {r['ttft_p95']:.2f} | {r['fs_p95_1_9']:.2f} / {r['fs_p95_all']:.2f} | "
                 f"{r['fresh_p50']} | {r['fallbacks']} | {'PASS' if r['pass'] else 'fail: ' + ', '.join(failed)} |")
    L.append("\n| layout | TTFT p50 by turn (0-9) | TTFT p50 by rep (turns 1-9) |\n|---|---|---|")
    for name, r in res.items():
        L.append(f"| {name} | {r['ttft_by_turn']} | {r['ttft_p50_by_rep']} |")
    L.append("\nNote text sent with Ziv's two facts:\n")
    for name in res:
        L.append(f"- {name}: `{EXAMPLE[name].strip()}`")
    for name, r in res.items():
        L.append(f"\n## {name}\n" + "\n".join(
            f"- {'OK ' if x['strict'] else 'NO '} t{x['idx']}: {x['text']}  — facts: {x['facts']}" for x in r["samples"]))
    (OUT / "note_probe2_C2.md").write_text("\n".join(L) + "\n")
    (OUT / "note_probe2_C2.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print("wrote", OUT / "note_probe2_C2.md")


def rescore(path=OUT / "note_probe2.json"):
    """C1: re-score Stage B's note_probe2.json (samples = 10 turn-8 replies, then 10 turn-9 replies per layout)."""
    d = json.loads(Path(path).read_text())
    out = {}
    for name, r in d.items():
        s = r["samples"]
        t8, t9 = [t for t, _ in s[:REPS]], [t for t, _ in s[REPS:]]
        out[name] = {"loose": sum("pickles" in t.lower() for t in t8) + sum("theo" in t.lower() for t in t9),
                     "strict": sum(strict_recall(t, "pickles") for t in t8) + sum(strict_recall(t, "theo") for t in t9),
                     "pickles_strict": sum(strict_recall(t, "pickles") for t in t8),
                     "theo_strict": sum(strict_recall(t, "theo") for t in t9),
                     "dont_know_old_regex": r["dont_know"],
                     "dont_know_strict_regex": sum(dont_know(t) for t in t8 + t9), "n": len(s)}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--rescore"]:
        rescore()
    else:
        main([a for a in args if a in LAYOUTS] or None)
