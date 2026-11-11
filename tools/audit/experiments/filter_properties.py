"""Step 3: spec-level properties of the CURRENT santa.safety.sanitize, on (a) the 924 stored raw replies and
(b) generated strings (random generator for rates + hypothesis for a shrunk minimal counter-example).

Properties
  P1 idempotence                 sanitize(sanitize(x)) == sanitize(x)
  P2 shape                       <= 1 '?' and <= MAX_WORDS words
  P3 negation survival           a negation in a kept sentence is still there
  P4 no invention                output words are an in-order subsequence of the input words (FALLBACK excluded)
  P5 question kept               raw (cleaned) ends with a question and fits MAX_WORDS -> output has a '?'
  P6 private data                looks_private(output) is False
  P7 order independence          (see order_dependence.py)
"""
import os
import random
import re
import tempfile

os.environ.setdefault("HYPOTHESIS_STORAGE_DIRECTORY", tempfile.mkdtemp(prefix="santa-audit-hyp-"))  # keep caches out of the repo
from hypothesis import HealthCheck, find, settings
from hypothesis import strategies as st

from _common import load_safety, load_turns, write

S = load_safety("cur")
cfg = __import__("santa_cur.config", fromlist=["x"])
MAXW = cfg.MAX_WORDS
NEG = re.compile(r"\b(?:not|never|no|don['’]t|doesn['’]t|didn['’]t|can['’]t|won['’]t|isn['’]t|aren['’]t|"
                 r"nobody|nothing|nowhere)\b|n['’]t\b", re.I)


def words(s):
    return re.findall(r"[a-z0-9]+(?:['’][a-z]+)?", s.lower())


def is_subseq(sub, full):
    it = iter(full)
    return all(any(w == x for x in it) for w in sub)


def sents(s):
    return [x for x in S._SENT_SPLIT.split(s) if x.strip()]


def best_source(o, cands):
    """Index of the cleaned-input sentence an output sentence came from (by word overlap)."""
    ow = words(o)
    best, score = None, 0.0
    for i, c in enumerate(cands):
        cw = words(c)
        if not cw or not ow:
            continue
        sc = len(set(ow) & set(cw)) / len(set(ow) | set(cw))
        if sc > score:
            best, score = i, sc
    return best, score


# ------------------------------------------------------------------ property functions (return None = ok, else str)
def p1(x):
    y = S.sanitize(x)
    z = S.sanitize(y)
    return None if y == z else f"once={y!r} twice={z!r}"


def p2(x):
    y = S.sanitize(x)
    if y.count("?") > 1:
        return f"{y.count('?')} '?': {y!r}"
    if len(y.split()) > MAXW:
        return f"{len(y.split())} words"
    return None


def p3(x):
    y, why = S.sanitize_ex(x)
    if why:
        return None
    src = sents(S._clean(x))
    for o in sents(y):
        i, sc = best_source(o, src)
        if i is None or sc < 0.5:
            continue
        a, b = len(NEG.findall(src[i])), len(NEG.findall(o))
        if b < a:
            return f"negation lost: in={src[i]!r} out={o!r}"
    # negations present in raw but missing after _clean (markup surgery) inside a sentence that survives
    rn, cn = len(NEG.findall(x)), len(NEG.findall(S._clean(x)))
    if cn < rn:
        return f"_clean removed a negation: raw={x!r} cleaned={S._clean(x)!r}"
    return None


def p4(x):
    y, why = S.sanitize_ex(x)
    if why:
        return None
    return None if is_subseq(words(y), words(x)) else f"invented/reordered: in={x!r} out={y!r}"


def p5(x):
    c = S._clean(x)
    ss = sents(c)
    if not ss or "?" not in ss[-1] or len(c.split()) > MAXW:
        return None
    y, why = S.sanitize_ex(x)
    if why:
        return None
    return None if "?" in y else f"question lost: cleaned={c!r} out={y!r}"


def p6(x):
    y = S.sanitize(x)
    return None if not S.looks_private(y) else f"private: {y!r}"


PROPS = {"P1 idempotence": p1, "P2 <=1 '?' and <=MAX_WORDS": p2, "P3 negation survives": p3,
         "P4 no invented/reordered words": p4, "P5 final question kept when it fits": p5,
         "P6 no private data in output": p6}

# ------------------------------------------------------------------ generators
OPENERS = ["Ho ho ho!", "Ho ho!", "Ooooh!", "Well, wow!", "Oh, Emma!", "Hey!", "Ho ho, Ziv!"]
STATEMENTS = ["I love that, Emma.", "That is not scary.", "It's **not** your fault.", "The dark is *never* scary!",
              "Mr. Snowman is here.", "Dr. Elf says hi!", "My elves are busy in the workshop.",
              "I can't wait to see you!", "Rudolph has a shiny red nose!", "You're a *star*!",
              "Mommy laughs!", "That sounds like so much fun!", "No, I'm not a robot.", "Jingle jingle!",
              "My reindeer are called Dasher and Dancer.", "Don't worry, Leo.", "Whoosh!",
              "I *love* dinosaurs—they're so big!", "A dinosaur and a pony and a rocket!"]
QUESTIONS = ["Do you like snow?", "Mittens, you said?", "What is your favorite toy?", "Or a reindeer too?",
             "Can you tell me more?", "Is it a big truck?!", "It's cold, isn't it?", "Which one would you pick first?"]
STAGE = ["*waves*", "*Giggle giggle!*", "(chuckles)", "*jingle jingle*", "*nibbles*", "*whoosh!*",
         "*gently pats shoulder*", "*Santa waves his hand*", "[a surprise]", "*sniffles*"]
TEASER = ["You know what?", "Guess what?"]
PRIVATE = ["I know your house, 12 Oak Lane!", "Call 555 123 4567!", "You live at forty two Maple Street."]


def gen_reply(rng):
    parts = []
    if rng.random() < 0.5:
        parts.append(rng.choice(OPENERS))
    for _ in range(rng.randint(1, 6)):
        r = rng.random()
        parts.append(rng.choice(QUESTIONS if r < 0.3 else STAGE if r < 0.45 else TEASER if r < 0.5
                                else PRIVATE if r < 0.52 else STATEMENTS))
    if rng.random() < 0.6:
        parts.append(rng.choice(QUESTIONS))
    sep = rng.choice([" ", " ", " ", "  ", "\n"])
    return sep.join(parts)


def gen_noise(rng):
    alphabet = "ab o h*_?!.,—()[]#  \nnot "
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))


# hypothesis strategy (structured) for shrinking
frag = st.sampled_from(OPENERS + STATEMENTS + QUESTIONS + STAGE + TEASER)
reply_st = st.lists(frag, min_size=1, max_size=8).map(" ".join)
noise_st = st.text(alphabet="ab oh*_?!.,—()[]#\n", max_size=40)

turns = load_turns()
raws = [t["raw"] for t in turns]
rng = random.Random(42)
gen_struct = [gen_reply(rng) for _ in range(20000)]
gen_noisy = [gen_noise(rng) for _ in range(20000)]

L = ["# Filter properties (generated by filter_properties.py)\n",
     f"Current santa/safety.py. Corpus: {len(raws)} stored raw replies. Generated: {len(gen_struct)} structured "
     f"Santa-like replies + {len(gen_noisy)} random-noise strings (seed 42). Counter-examples: up to 1 hypothesis-"
     f"shrunk minimal example + the shortest distinct failures.\n",
     "| Property | 924 stored replies: fail | structured generated: fail | noise generated: fail |",
     "|---|---|---|---|"]
details = []
for name, fn in PROPS.items():
    res = {}
    for label, data in (("corpus", raws), ("struct", gen_struct), ("noise", gen_noisy)):
        fails = []
        for x in data:
            try:
                r = fn(x)
            except Exception as e:  # a crash is a failure too
                r = f"CRASH {type(e).__name__}: {e}"
            if r:
                fails.append((x, r))
        res[label] = fails
    L.append(f"| {name} | {len(res['corpus'])}/{len(raws)} ({100*len(res['corpus'])/len(raws):.1f}%) | "
             f"{len(res['struct'])}/{len(gen_struct)} ({100*len(res['struct'])/len(gen_struct):.1f}%) | "
             f"{len(res['noise'])}/{len(gen_noisy)} ({100*len(res['noise'])/len(gen_noisy):.1f}%) |")
    details.append(f"\n### {name}\n")
    shrunk = None
    for strat in (reply_st, noise_st):
        try:
            shrunk = find(strat, lambda x: bool(fn(x)),
                          settings=settings(max_examples=3000, database=None,
                                            suppress_health_check=list(HealthCheck)))
            break
        except Exception:
            continue
    if shrunk is not None:
        details.append(f"- hypothesis-shrunk minimal: `{shrunk!r}` -> {fn(shrunk)}")
    seen = set()
    for label in ("corpus", "struct", "noise"):
        for x, r in sorted(res[label], key=lambda p: len(p[0]))[:40]:
            key = r[:50]
            if key in seen:
                continue
            seen.add(key)
            details.append(f"- [{label}] `{x[:220]!r}` -> {r[:300]}")
            if len(seen) >= 5:
                break
        if len(seen) >= 5:
            break
L += details
write("filter_properties.md", "\n".join(L) + "\n")
