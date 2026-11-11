"""Steps 3 (P7 + monotonic quality) and 4a (intervention rate), plus the same metrics for every historical
version of sanitize, on the 924 stored raw replies. Also writes the stratified 60-pair sample for step 4b.

Classification of (raw -> heard), all heuristics stated here so they can be checked:
  fallback            heard == that version's FALLBACK
  dropped             >=1 sentence of clean(raw) (not a pure stage direction) is absent from heard
  cut                 the word cap cut a sentence (heard sentence is a strict prefix of a raw sentence, ends '!')
  q_demoted           a sentence that was a question in raw is in heard as a statement
  q_lost              raw had a '?', heard has none (and is not the fallback)
  neg_lost            fewer negation words in heard's kept sentences than in their raw source
  art_punct           '.!' / '.?' / '?.' sequence not present in raw
  art_dangling        a heard sentence (not the first) starts with Or/And/But/So/Then/Also and its raw predecessor
                      was dropped
  art_stage           a stand-alone *span* / (span) from raw that is not a sound word is spoken (e.g. "nibbles")
  answer_lost         the child asked a question; >=1 substantive raw statement (>=5 words, not a question) was
                      dropped and heard keeps none
  substance_lost      same as answer_lost but for any child turn
  echo_q              heard = [opener] + a <=4-word demoted echo + a question, with raw middle sentences dropped
"""
import difflib
import itertools
import json
import random
import re
from collections import Counter, defaultdict

from _common import OUT, SOUNDS, VERSIONS, W, load_safety, load_turns, standalone_spans, write

CUR = load_safety("cur")
NEG = re.compile(r"\b(?:not|never|no|nobody|nothing)\b|n['’]t\b", re.I)
CONNECT = re.compile(r"^(?:or|and|but|so|then|also|because)\b", re.I)
QWORDS = re.compile(r"^\s*(?:\w+:\s*)?(?:what|who|where|why|how|when|which|can|could|do|does|did|are|is|will|would)\b",
                    re.I)


def sents(s):
    return [x for x in CUR._SENT_SPLIT.split(s) if x.strip()]


def contains_run(hay, needle):
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def classify(t, heard, fallback):
    raw = t["raw"]
    tags = set()
    if heard == fallback:
        return {"fallback"}
    clean = CUR._clean(raw)
    rs = sents(clean)
    hs = sents(heard)
    hw = W(heard)
    kept_idx = []
    for i, s in enumerate(rs):
        sw = W(s)
        if not sw:
            continue
        if contains_run(hw, sw):
            kept_idx.append(i)
        elif CUR._is_direction(s):
            continue
        else:
            # partially kept (word cap)?
            if hs and len(W(hs[-1])) >= 3 and sw[:len(W(hs[-1]))] == W(hs[-1]) and len(W(hs[-1])) < len(sw):
                tags.add("cut")
                kept_idx.append(i)
            else:
                tags.add("dropped")
    dropped_idx = [i for i in range(len(rs)) if i not in kept_idx and W(rs[i]) and not CUR._is_direction(rs[i])]
    # questions
    raw_q = [i for i, s in enumerate(rs) if "?" in s]
    for i in raw_q:
        if i in kept_idx:
            sw = W(rs[i])
            for h in hs:
                if W(h) == sw and "?" not in h:
                    tags.add("q_demoted")
    if "?" in raw and "?" not in heard:
        tags.add("q_lost")
    # negation
    if len(NEG.findall(heard)) < sum(len(NEG.findall(rs[i])) for i in kept_idx if "cut" not in tags):
        tags.add("neg_lost")
    # artifacts
    if re.search(r"\.[!?]|\?\.", heard) and not re.search(r"\.[!?]|\?\.", clean):
        tags.add("art_punct")
    for j, h in enumerate(hs[1:], 1):
        if CONNECT.match(h.strip()):
            src = next((i for i in kept_idx if W(rs[i]) == W(h)), None)
            if src is not None and src > 0 and (src - 1) in dropped_idx:
                tags.add("art_dangling")
    for inner in standalone_spans(raw):
        iw = W(inner)
        if iw and not CUR._is_direction(inner) and contains_run(hw, iw) and not all(w in SOUNDS for w in iw):
            tags.add("art_stage")
    # substance
    subst = lambda s: "?" not in s and len(W(s)) >= 5 and not CUR._is_opener(s)  # noqa: E731
    if any(subst(rs[i]) for i in dropped_idx) and not any(subst(h) for h in hs):
        tags.add("substance_lost")
        if "?" in t["child"] or QWORDS.match(t["child"]):
            tags.add("answer_lost")
    # echo + question with middle dropped
    body = hs[1:] if hs and CUR._is_opener(hs[0]) else hs
    if len(body) == 2 and len(W(body[0])) <= 4 and "?" not in body[0] and "?" in body[1] and "dropped" in tags \
            and any("?" in rs[i] and W(rs[i]) == W(body[0]) for i in range(len(rs))):
        tags.add("echo_q")
    return tags


MATERIAL = {"fallback", "dropped", "cut", "q_demoted", "q_lost", "neg_lost"}
ARTIFACT = {"art_punct", "art_dangling", "art_stage"}
LOST = {"answer_lost"}

turns = load_turns()
N = len(turns)
files = sorted({t["file"] for t in turns})
short = {t["file"]: t["short"] for t in turns}

L = ["# Quality of raw -> heard, by filter version and by result file (generated by quality.py)\n",
     "Heuristic tag definitions are in the docstring of quality.py. 'material' = fallback, dropped, cut, "
     "q_demoted, q_lost or neg_lost (pure markup removal is NOT material).\n"]

# ------------------------------------------------------------------ per version
L.append("## Same 924 raw replies through every historical version of sanitize\n")
L.append("| Version | changed at all | material change | dropped | q_demoted | q_lost (0 '?') | fallback | "
         "art_punct | art_dangling | art_stage | answer_lost | echo_q | any artifact or answer_lost |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
per_version = {}
for v in VERSIONS:
    S = load_safety(v)
    tags_all = []
    for t in turns:
        h = S.sanitize(t["raw"])
        tg = classify(t, h, S.FALLBACK)
        tags_all.append((t, h, tg))
    per_version[v] = tags_all
    c = Counter(x for _, _, tg in tags_all for x in tg)
    changed = sum(1 for t, h, _ in tags_all if " ".join(h.split()) != " ".join(t["raw"].split()))
    mat = sum(1 for _, _, tg in tags_all if tg & MATERIAL)
    bad = sum(1 for _, _, tg in tags_all if tg & (ARTIFACT | LOST))
    pc = lambda n: f"{n} ({100*n/N:.1f}%)"  # noqa: E731
    L.append(f"| {v} | {pc(changed)} | {pc(mat)} | {pc(c['dropped'])} | {pc(c['q_demoted'])} | {pc(c['q_lost'])} | "
             f"{pc(c['fallback'])} | {c['art_punct']} | {c['art_dangling']} | {c['art_stage']} | "
             f"{c['answer_lost']} | {c['echo_q']} | {pc(bad)} |")
L.append(f"\nDenominator: {N} stored raw replies in every cell. 'idx' = git index (21:10), s0 = before round 1, "
         "s1 = after round 1, s2 = after round 2, cur = after round 3.")

# ------------------------------------------------------------------ per file, current
cur = per_version["cur"]
L.append("\n## 4a. Intervention rate per result file (current filter)\n")
L.append("| File | n | material change (intervention) | dropped | q_demoted | fallback | artifact | answer_lost | "
         "artifact or answer_lost |")
L.append("|---|---|---|---|---|---|---|---|---|")
for f in files:
    R = [(t, h, tg) for t, h, tg in cur if t["file"] == f]
    n = len(R)
    c = Counter(x for _, _, tg in R for x in tg)
    mat = sum(1 for _, _, tg in R if tg & MATERIAL)
    art = sum(1 for _, _, tg in R if tg & ARTIFACT)
    bad = sum(1 for _, _, tg in R if tg & (ARTIFACT | LOST))
    L.append(f"| {short[f]} | {n} | {mat} ({100*mat/n:.1f}%) | {c['dropped']} | {c['q_demoted']} | {c['fallback']} | "
             f"{art} | {c['answer_lost']} | {bad} ({100*bad/n:.1f}%) |")
for grp, key in (("persona", "persona"), ("model family", "family")):
    L.append(f"\nBy {grp}: " + "; ".join(
        f"{g}: material {sum(1 for t,_,tg in cur if t[key]==g and tg & MATERIAL)}/{sum(1 for t,_,_ in cur if t[key]==g)}, "
        f"artifact-or-answer-lost {sum(1 for t,_,tg in cur if t[key]==g and tg & (ARTIFACT|LOST))}"
        for g in sorted({t[key] for t in turns})))

# ------------------------------------------------------------------ examples of each tag (current)
L.append("\n## Examples per tag (current filter, up to 4 each)\n")
for tag in ["art_punct", "art_dangling", "art_stage", "answer_lost", "echo_q", "q_lost", "neg_lost", "cut"]:
    ex = [(t, h) for t, h, tg in cur if tag in tg]
    L.append(f"\n**{tag}** ({len(ex)}):")
    for t, h in ex[:4]:
        L.append(f"- [{t['short']}] child: {t['child']!r}\n  - raw: {t['raw'][:260]!r}\n  - heard: {h!r}")

# ------------------------------------------------------------------ P7 order independence
C, Q, T = CUR._clean, CUR._one_question, CUR._truncate
PASSES = {"C": C, "Q": Q, "T": T}
orders = {"current Q(T(Q(C)))": lambda x: Q(T(Q(C(x))))}
for perm in itertools.permutations("CQT"):
    orders["".join(perm) + " (left applied first)"] = (lambda p: (lambda x: PASSES[p[2]](PASSES[p[1]](PASSES[p[0]](x)))))(perm)
base = {t["raw"]: orders["current Q(T(Q(C)))"](t["raw"]) for t in turns}
L.append("\n## P7. Order dependence of the three passes (current pass implementations; blocklist/private checks "
         "excluded)\n")
L.append("| Order | replies whose output differs from the current order (of 924) |")
L.append("|---|---|")
anydiff = set()
for name, fn in orders.items():
    if name.startswith("current"):
        continue
    d = [t for t in turns if fn(t["raw"]) != base[t["raw"]]]
    anydiff |= {id(t) for t in d}
    L.append(f"| {name} | {len(d)} ({100*len(d)/N:.1f}%) |")
L.append(f"\nReplies whose result depends on pass order under at least one alternative order: {len(anydiff)}/{N} "
         f"({100*len(anydiff)/N:.1f}%)")
ex = [t for t in turns if orders["CTQ (left applied first)"](t["raw"]) != base[t["raw"]]][:3]
for t in ex:
    L.append(f"- raw: {t['raw'][:200]!r}\n  - current: {base[t['raw']]!r}\n  - C,T,Q (round-1 order): "
             f"{orders['CTQ (left applied first)'](t['raw'])!r}")

write("quality.md", "\n".join(L) + "\n")

# ------------------------------------------------------------------ 4b stratified sample of 60
random.seed(2026)
sample = []
per_file = {f: [(t, h, tg) for t, h, tg in cur if t["file"] == f] for f in files}
quota = {f: 9 if i < 4 else 8 for i, f in enumerate(files)}  # 4*9 + 3*8 = 60
for f in files:
    R = [x for x in per_file[f] if x[2] & MATERIAL]
    R.sort(key=lambda x: difflib.SequenceMatcher(None, x[0]["raw"], x[1]).ratio())
    take = R[:max(0, quota[f] - 3)]  # most changed
    rest = [x for x in R[len(take):]]
    take += random.sample(rest, min(3, len(rest)))
    if len(take) < quota[f]:  # files with few changes: fill with unchanged-material replies
        others = [x for x in per_file[f] if x not in take]
        take += random.sample(others, quota[f] - len(take))
    sample += take
rows = []
for k, (t, h, tg) in enumerate(sample, 1):
    rows.append({"id": k, "file": t["short"], "scenario": t["scenario"], "sample": t["sample"], "idx": t["idx"],
                 "child": t["child"], "raw": t["raw"], "heard": h, "auto_tags": sorted(tg)})
(OUT / "sample60.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
md = ["# 60-pair stratified sample (raw -> heard, current filter). Labels are in labels60.md\n"]
for r in rows:
    md.append(f"## #{r['id']} [{r['file']}] {r['scenario']} s{r['sample']} i{r['idx']}\n- child: {r['child']}\n"
              f"- raw: {r['raw']}\n- heard: {r['heard']}\n- auto: {r['auto_tags']}\n")
write("sample60.md", "\n".join(md))
