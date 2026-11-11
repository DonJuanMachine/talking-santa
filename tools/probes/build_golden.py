#!/usr/bin/env python3
"""Build tests/spec/golden.jsonl (read-only on evals/results and tools/probes/out).

Rows: the 924 stored raw replies (7 result files) + the 132 e4b persona-v1 replies from Stage A (tools/probes/out/
shape-v1.jsonl). Every row says where it came from. Ministral rows are marked adversarial (test data only: the
filter is not tuned to them).
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "spec" / "golden.jsonl"
PERSONA = {"ai_gemma4.json": "v1", "ai_gemma4_e4b.json": "v1"}  # all other stored files: v2 (MANIFEST)

rows = []
for f in sorted((ROOT / "evals" / "results").glob("ai_*.json")):
    d = json.loads(f.read_text())
    for t in d["turns"]:
        rows.append({"source": f"stored:{f.name}", "model": d["model"], "persona": PERSONA.get(f.name, "v2"),
                     "adversarial": "ministral" in f.name, "kind": t["kind"], "scenario": t["scenario"],
                     "sample": t["sample"], "idx": t["idx"], "speaker": t.get("speaker"), "child": t["child"],
                     "raw": t["raw"]})
for line in (ROOT / "tools" / "probes" / "out" / "shape-v1.jsonl").read_text().splitlines():
    t = json.loads(line)
    rows.append({"source": "stageA:e4b-v1", "model": "ai/gemma4:e4b", "persona": "v1", "adversarial": False,
                 "kind": t["kind"], "scenario": t["scenario"], "sample": t["sample"], "idx": t["idx"],
                 "speaker": t.get("speaker"), "child": t["child"], "raw": t["raw"]})
OUT.parent.mkdir(exist_ok=True)
text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
OUT.write_text(text)
n_stored = sum(r["source"].startswith("stored:") for r in rows)
print(f"wrote {OUT}: {len(rows)} rows ({n_stored} stored, {len(rows) - n_stored} stageA e4b v1), "
      f"sha256 {hashlib.sha256(text.encode()).hexdigest()[:12]}")
