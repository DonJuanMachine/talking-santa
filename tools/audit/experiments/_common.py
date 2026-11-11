"""Shared helpers for the audit experiments. Read-only on the repo.

- load_turns(): the 924 stored turns from evals/results/ai_*.json (read only).
- load_safety(tag): import one historical version of santa/safety.py (+ its config.py) as an isolated
  package copied into a temp dir OUTSIDE the repo, so several versions can be compared side by side.

Versions:
  idx  = git index (staged at 2026-11-04 21:10), read with `git show :path` (read-only git)
  s0   = .snapshots/pre-fix-20261104-2326   (code before round 1; == evals/backup/pre-fix-2241)
  s1   = .snapshots/pre-fix2-20261105-0617  (after round 1)
  s2   = .snapshots/pre-fix3-20261105-0628  (after round 2)
  cur  = santa/                              (after round 3)
"""
import importlib
import re
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "evals" / "results"
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

SNAP = {
    "s0": ROOT / ".snapshots" / "pre-fix-20261104-2326",
    "s1": ROOT / ".snapshots" / "pre-fix2-20261105-0617",
    "s2": ROOT / ".snapshots" / "pre-fix3-20261105-0628",
    "cur": ROOT,
}
VERSIONS = ["idx", "s0", "s1", "s2", "cur"]

SHORT = {
    "ai_gemma4.json": "gemma4-12B v1", "ai_gemma4_e4b.json": "e4b v1", "ai_gemma4_e4b_v2.json": "e4b v2",
    "ai_gemma4_v2.json": "gemma4-12B v2", "ai_ministral3_14B.json": "ministral14B v2",
    "ai_ministral3_8B_Q4_K_M.json": "ministral8B-Q4 v2", "ai_ministral_3_8b_instruct.json": "ministral8B-instr v2",
}
PERSONA = {"ai_gemma4.json": "v1", "ai_gemma4_e4b.json": "v1"}  # all others v2 (MANIFEST, inferred)
FAMILY = {"ai_gemma4.json": "gemma4-12B", "ai_gemma4_v2.json": "gemma4-12B", "ai_gemma4_e4b.json": "gemma4-e4b",
          "ai_gemma4_e4b_v2.json": "gemma4-e4b"}


def load_turns():
    out = []
    for f in sorted(RESULTS.glob("ai_*.json")):
        d = json.loads(f.read_text())
        for t in d["turns"]:
            t = dict(t)
            t["file"] = f.name
            t["model"] = d["model"]
            t["short"] = SHORT.get(f.name, f.name)
            t["persona"] = PERSONA.get(f.name, "v2")
            t["family"] = FAMILY.get(f.name, "ministral")
            out.append(t)
    return out


_TMP = Path(tempfile.mkdtemp(prefix="santa-audit-"))
_loaded = {}


def version_source(tag: str, rel: str) -> str:
    if tag == "idx":
        return subprocess.run(["git", "-C", str(ROOT), "show", f":{rel}"], capture_output=True, text=True,
                              check=True).stdout
    return (SNAP[tag] / rel).read_text()


def load_safety(tag: str):
    """Return the safety module of version `tag` (package santa_<tag> in a temp dir)."""
    if tag in _loaded:
        return _loaded[tag]
    pkg = _TMP / f"santa_{tag}"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "config.py").write_text(version_source(tag, "santa/config.py"))
    (pkg / "safety.py").write_text(version_source(tag, "santa/safety.py"))
    if str(_TMP) not in sys.path:
        sys.path.insert(0, str(_TMP))
    mod = importlib.import_module(f"santa_{tag}.safety")
    _loaded[tag] = mod
    return mod


def load_bench_rule_flags():
    """bench.rule_flags and its regexes WITHOUT importing evals/bench.py (which patches santa.memory globally
    and creates folders at import). We exec only the auto-check block of the current bench.py."""
    src = (ROOT / "evals" / "bench.py").read_text()
    start = src.index("# ----------------------------------------------------------------- auto checks")
    end = src.index("_STOP = set(")
    import re as _re
    cur = load_safety("cur")
    ns = {"re": _re, "config": cur.config if hasattr(cur, "config") else None, "safety": cur}
    ns["config"] = importlib.import_module("santa_cur.config")
    exec(compile(src[start:end], "bench_autocheck", "exec"), ns)
    return ns


def sentences(text: str, safety_mod):
    return safety_mod._SENT_SPLIT.split(text) if hasattr(safety_mod, "_SENT_SPLIT") else \
        __import__("re").split(r"(?<=[.!?])\s+", text)


SOUNDS = {"jingle", "whoosh", "ho", "zoom", "beep", "choo", "ding", "dong", "brr", "vroom", "ring", "swish",
          "woosh", "whee", "roar", "rooar", "rawr", "boom", "honk", "toot", "moo", "meow", "woof", "neigh",
          "clop", "tick", "tock", "pop", "splash", "crunch", "yum", "yummy", "mmm", "sparkle", "twinkle",
          "purr", "purrr", "ooh", "oooh", "wow", "hooray", "yay"}

def W(s):
    return re.findall(r"[a-z0-9]+(?:['’][a-z]+)?", s.lower())


def standalone_spans(raw):
    out = []
    for m in re.finditer(r"\*+([^*]+?)\*+|\(([^)]*)\)", raw):
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        before = raw[:m.start()].rstrip()
        after = raw[m.end():].lstrip()
        alone_before = (not before) or before[-1] in ".!?…—-" or before.endswith("...")
        alone_after = (not after) or after[0].isupper() or after[0] in ".!?…—-"
        if alone_before and alone_after:
            out.append(inner.strip())
    return out


def write(name: str, text: str):
    (OUT / name).write_text(text)
    print(f"wrote {OUT / name}")
