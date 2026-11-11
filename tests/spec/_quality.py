"""Heuristic raw -> heard classifier, copied from the audit (tools/audit/experiments/quality.py, `classify`) so the
golden-corpus numbers are comparable with the audit's "artifact or lost answer" table (8.8% for today's filter).
Adapted only to call santa.spec instead of a historical safety module. Not imported from tools/audit on purpose.

Tags (as in the audit):
  fallback       heard == FALLBACK
  dropped        a sentence of clean(raw) (not a pure stage direction) is absent from heard
  q_demoted      a sentence that was a question in raw is in heard as a statement
  q_lost         raw had a '?', heard has none (and is not the fallback)
  art_punct      '.!' / '.?' / '?.' sequence not present in raw
  art_dangling   a heard sentence (not the first) starts with Or/And/But/So/Then/Also and its raw predecessor was dropped
  art_stage      a stand-alone *span* / (span) from raw that is not a sound word is spoken
  answer_lost    the child asked a question; >= 1 substantive raw statement (>= 5 words, not a question) was dropped
                 and heard keeps none
"""
import re

from santa import spec

NEG = re.compile(r"\b(?:not|never|no|nobody|nothing)\b|n['’]t\b", re.I)
CONNECT = re.compile(r"^(?:or|and|but|so|then|also|because)\b", re.I)
QWORDS = re.compile(r"^\s*(?:\w+:\s*)?(?:what|who|where|why|how|when|which|can|could|do|does|did|are|is|will|would)\b",
                    re.I)
ARTIFACT = {"art_punct", "art_dangling", "art_stage"}
LOST = {"answer_lost"}
W = spec.words_of


def sents(s):
    return spec.split_sentences(s)


def contains_run(hay, needle):
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def standalone_spans(raw):
    """The audit's definition (tools/audit/experiments/_common.py), kept independent of spec's own rule."""
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


def classify(raw, child, heard):
    tags = set()
    if heard == spec.FALLBACK:
        return {"fallback"}
    rs = sents(spec.clean(raw))
    hs = sents(heard)
    hw = W(heard)
    kept_idx = []
    for i, s in enumerate(rs):
        sw = W(s)
        if not sw:
            continue
        if contains_run(hw, sw):
            kept_idx.append(i)
        elif not spec._is_direction(s):
            tags.add("dropped")
    dropped_idx = [i for i in range(len(rs)) if i not in kept_idx and W(rs[i]) and not spec._is_direction(rs[i])]
    for i in [i for i, s in enumerate(rs) if "?" in s]:
        if i in kept_idx:
            for h in hs:
                if W(h) == W(rs[i]) and "?" not in h:
                    tags.add("q_demoted")
    if "?" in raw and "?" not in heard:
        tags.add("q_lost")
    if re.search(r"\.[!?]|\?\.", heard) and not re.search(r"\.[!?]|\?\.", raw):
        tags.add("art_punct")
    for h in hs[1:]:
        if CONNECT.match(h.strip()):
            src = next((i for i in kept_idx if W(rs[i]) == W(h)), None)
            if src is not None and src > 0 and (src - 1) in dropped_idx:
                tags.add("art_dangling")
    for inner in standalone_spans(raw):
        iw = W(inner)
        if iw and not spec._is_direction(inner) and contains_run(hw, iw) and not all(w in spec.SOUNDS for w in iw):
            tags.add("art_stage")
    subst = lambda s: "?" not in s and len(W(s)) >= 5 and not spec.is_opener(s)  # noqa: E731
    if any(subst(rs[i]) for i in dropped_idx) and not any(subst(h) for h in hs):
        if "?" in child or QWORDS.match(child):
            tags.add("answer_lost")
    return tags
