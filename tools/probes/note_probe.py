#!/usr/bin/env python3
"""B7 diagnosis (live, ai/gemma4:e4b only): the smoke test found long_session recall at turns 8-9 dropping to
Pickles 2/5, Theo 4/5 ("I don't know your cat's name, Ziv"). Compare facts-note wordings and trim block sizes,
in this process only (persona.FACTS_NOTE / config.HISTORY_TRIM_BLOCK monkeypatched; no product file edited).

Writes tools/probes/out/note_probe.md and .json.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
os.environ["SANTA_PROFILES"] = str(Path(tempfile.mkdtemp(prefix="santa-note-")) / "profiles.json")
sys.path.insert(0, str(ROOT))

from santa import config, memory, persona  # noqa: E402
from santa.brain import Santa  # noqa: E402

MODEL = "ai/gemma4:e4b"
def _sentences(name, facts):
    return " ".join((f if f.lower().startswith(name.lower()) else f"{name} {f}").rstrip(".") + "." for f in facts)


class PrefixSanta(Santa):
    """Variant D: the note goes BEFORE the child's line, facts as full sentences."""

    def build_messages(self, speaker, text):
        msgs, label, red = super().build_messages(speaker, text)
        facts = (self.profiles.get(speaker) or {}).get("facts", [])[-6:] if speaker else []
        if facts:
            msgs[-1] = {"role": "user", "content": f"(Santa knows: {_sentences(speaker, facts)})\n{label}"}
        return msgs, label, red


class SentenceSanta(Santa):
    """Variant E: the note after the child's line, facts as full sentences."""

    def build_messages(self, speaker, text):
        msgs, label, red = super().build_messages(speaker, text)
        facts = (self.profiles.get(speaker) or {}).get("facts", [])[-6:] if speaker else []
        if facts:
            msgs[-1] = {"role": "user", "content": f"{label}\n(Santa remembers: {_sentences(speaker, facts)})"}
        return msgs, label, red


class OldLayoutSanta(Santa):
    """Variant F: today's OLD layout with persona v1: the speaker's facts in the system prompt ("knows: ..."),
    no note on the user turn. Diagnoses persona vs layout (slow TTFT expected: the system prompt changes)."""

    def build_messages(self, speaker, text):
        msgs, label, red = super().build_messages(speaker, text)
        msgs[0] = {"role": "system", "content": persona.build_system_prompt(self.profiles, speaker)}
        msgs[-1] = {"role": "user", "content": label}
        return msgs, label, red


class SystemTailSanta(Santa):
    """Variant G: constant system prompt + the speaker's facts appended at its very END (no user-turn note).
    Only what follows the system prompt (the history) is re-processed when the speaker or facts change."""

    def build_messages(self, speaker, text):
        msgs, label, red = super().build_messages(speaker, text)
        facts = (self.profiles.get(speaker) or {}).get("facts", [])[-6:] if speaker else []
        tail = f"\n\nTHE CHILD TALKING NOW: {speaker}. Santa remembers: {_sentences(speaker, facts)}" if facts else ""
        msgs[0] = {"role": "system", "content": msgs[0]["content"] + tail}
        msgs[-1] = {"role": "user", "content": label}
        return msgs, label, red


class LateSystemSanta(Santa):
    """Variant H: a second, short system message right before the child's turn (end of the prompt: cache-friendly)."""

    def build_messages(self, speaker, text):
        msgs, label, red = super().build_messages(speaker, text)
        facts = (self.profiles.get(speaker) or {}).get("facts", [])[-6:] if speaker else []
        msgs[-1] = {"role": "user", "content": label}
        if facts:
            msgs.insert(len(msgs) - 1, {"role": "system", "content": f"Santa remembers: {_sentences(speaker, facts)}"})
        return msgs, label, red


VARIANTS = {
    "A current note, trim 8": ("\n(Santa remembers about {name}: {facts})", 8),
    "A current note, trim 4": ("\n(Santa remembers about {name}: {facts})", 4),
    "B 'Santa already knows' note, trim 8": ("\n(Santa already knows this about {name}: {facts}.)", 8),
    "C 'told Santa earlier' note, trim 8": ("\n(Earlier, {name} told Santa: {facts}.)", 8),
    "D note BEFORE the line, full sentences, trim 8": (None, 8),
    "E note after the line, full sentences, trim 8": (None, 8),
    "F OLD layout (facts in system prompt), persona v1, trim 8": (None, 8),
    "G facts at the END of the constant system prompt, trim 8": (None, 8),
    "H second system message before the child's turn, trim 8": (None, 8),
}
ONLY = sys.argv[1:]


def main():
    spec_ = importlib.util.spec_from_file_location("bench", ROOT / "evals" / "bench.py")
    bench = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(bench)          # memory.save -> no-op in this process
    memory.extract_facts = bench.REAL_EXTRACT
    scen = next(x for x in bench.SCENARIOS if x["id"] == "long_session_memory")
    subprocess.run(["docker", "model", "unload", "--all"], capture_output=True)
    time.sleep(2)
    t_all = time.perf_counter()
    res = {}
    for name, (note, block) in VARIANTS.items():
        if ONLY and name[0] not in ONLY:
            continue
        cls = {"D": PrefixSanta, "E": SentenceSanta, "F": OldLayoutSanta, "G": SystemTailSanta, "H": LateSystemSanta}.get(name[0], Santa)
        persona.FACTS_NOTE = note or "\n(Santa remembers about {name}: {facts})"
        config.HISTORY_TRIM_BLOCK = block
        rows = []
        for rep in range(5):
            s = cls(model=MODEL, profiles={"Emma": {"facts": []}, "Leo": {"facts": []}, "Ziv": {"facts": []}})
            s.warm_up()
            for i, tn in enumerate(scen["turns"]):
                s.set_active(tn["s"])
                r = s.reply_ex(tn["s"], tn["t"])
                if r.error:
                    print("  model error:", r.error, flush=True)
                s.remember(tn["s"], tn["t"])
                rows.append({"rep": rep, "idx": i, "text": r.text, "ttft": r.ttft,
                             "facts": {k: list(v["facts"]) for k, v in s.profiles.items()}})
        t8 = [x for x in rows if x["idx"] == 8]
        t9 = [x for x in rows if x["idx"] == 9]
        res[name] = {"pickles": sum("pickles" in x["text"].lower() for x in t8),
                     "theo": sum("theo" in x["text"].lower() for x in t9),
                     "dont_know": sum("know" in x["text"].lower() and ("don't" in x["text"].lower() or "do not" in x["text"].lower())
                                      for x in t8 + t9),
                     "facts_have_pickles": sum(any("pickles" in f.lower() for f in x["facts"]["Ziv"]) for x in t8),
                     "facts_have_theo": sum(any("theo" in f.lower() for f in x["facts"]["Emma"]) for x in t9),
                     "ttft_p50": sorted(x["ttft"] for x in rows if x["idx"] >= 1)[len([x for x in rows if x["idx"] >= 1]) // 2],
                     "samples": [x["text"] for x in t8 + t9]}
        print(name, {k: v for k, v in res[name].items() if k != "samples"}, flush=True)
    subprocess.run(["docker", "model", "unload", "--all"], capture_output=True)
    L = ["# Facts-note diagnosis (generated by tools/probes/note_probe.py)\n",
         f"long_session_memory, 5 reps per variant, persona v1, extraction via remember(). Model time "
         f"{(time.perf_counter() - t_all) / 60:.1f} min.\n",
         "| variant | turn 8 says Pickles | turn 9 says Theo | replies saying \"I don't know\" (of 10) | Pickles in Ziv's facts | Theo in Emma's facts | TTFT p50 turns 1-9 |",
         "|---|---|---|---|---|---|---|"]
    for name, r in res.items():
        L.append(f"| {name} | {r['pickles']}/5 | {r['theo']}/5 | {r['dont_know']} | {r['facts_have_pickles']}/5 | "
                 f"{r['facts_have_theo']}/5 | {r['ttft_p50']:.2f} |")
    for name, r in res.items():
        L.append(f"\n## {name}\n" + "\n".join(f"- {t}" for t in r["samples"]))
    name_md = "note_probe.md" if not ONLY else f"note_probe_{''.join(ONLY)}.md"
    (OUT / name_md).write_text("\n".join(L) + "\n")
    (OUT / name_md.replace(".md", ".json")).write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print("wrote", OUT / name_md)


if __name__ == "__main__":
    main()
