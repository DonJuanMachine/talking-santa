#!/usr/bin/env python3
"""Conversation guide, live (santa/guide.py, 2026-11-25). ai/gemma4:e4b through Docker Model Runner.

Fresh Santa per session, started the way the call page starts a call (the canned greeting in history), with a temp
call log and made-up children (Emma: called yesterday, likes snow angels, has a cat named Mittens, wants a drawing pad;
Leo: new, no facts). Nothing is saved: remember() and end_call() are never called.

  R  returning child   "I'm Emma" / "I'm good" / "I made a snowman"
  N  new child         "I'm Leo" / "good" / "I like trucks"
  L  nice list         "I'm Emma" / "Am I on the nice list?" / "Am I on the naughty list?"
  G  guest nice list   (no name) "am I on the nice list Santa?"
  D  dreams            child brings up a dream, then says goodbye at 5:30 PM (no "sweet dreams" allowed)
  E  evening goodbye   goodbye at 7:30 PM ("sweet dreams" allowed, not required)
  S  sad first turn    "I'm Emma. I'm sad, my fish died"

Usage: <venv>/bin/python tools/probes/guide_probe.py [--runs 10] [--control]   (--control: SANTA_GUIDE=0)
Writes tools/probes/out/guide_probe[_control].md (gitignored).
"""
import argparse
import copy
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
TMP = Path(tempfile.mkdtemp(prefix="santa-guide-"))
os.environ["SANTA_PROFILES"] = str(TMP / "profiles.json")
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--runs", type=int, default=10)
ap.add_argument("--control", action="store_true")
A = ap.parse_args()
if A.control:
    os.environ["SANTA_GUIDE"] = "0"

from santa import calllog, config  # noqa: E402
from santa.brain import Santa  # noqa: E402
from santa.web import canned  # noqa: E402

config.CALLS_PATH = TMP / "calls.json"
KIDS = {"Emma": {"age": 4, "facts": ["likes snow angels", "has a cat named Mittens", "wants a drawing pad"]},
        "Leo": {"age": 3, "facts": []}}
AFTERNOON = datetime(2026, 11, 25, 16, 30)


def reset_call_log():
    """Every session sees the same history: Emma called once, yesterday; Leo never (the probe's own calls are logged)."""
    calllog.remove()
    calllog.record("Emma", AFTERNOON - timedelta(days=1, hours=1))

HOW = re.compile(r"how are you|how're you|how is your day|how's your day|how was your day|how are things|"
                 r"how have you been|how do you feel|how are you feeling|how you are|how you're doing|how are you doing|"
                 r"how is (?:it going|everything|your)|how's (?:it going|everything)", re.I)
AGAIN = re.compile(r"\bagain\b|welcome back|so (?:glad|happy) you called back", re.I)
COND = re.compile(r"\bif you\b|as long as|keep (?:being|up)|stay (?:good|nice)|be good|remember to|try to be", re.I)
DREAM_Q = re.compile(r"[^.!?]*\bdream(?!\s+gift)[^.!?]*\?", re.I)
SWEET = re.compile(r"sweet dreams", re.I)
LIKE_Q = re.compile(r"[^.!?]*\b(like|love|favou?rite|play|fun)\b[^.!?]*\?", re.I)
FACT_Q = re.compile(r"[^.!?]*\b(snow angels?|mittens|cat|kitty)\b[^.!?]*\?", re.I)


def session(now=AFTERNOON):
    reset_call_log()
    s = Santa(call_log=True, profiles=copy.deepcopy(KIDS))
    s.clock = lambda: now
    s.history.append({"role": "assistant", "content": canned.GREETING_SAID})
    return s


def turn(s, speaker, text):
    r = s.reply_ex(speaker, text)
    return r


SCRIPTS = {
    "R": (AFTERNOON, [("Emma", "I'm Emma"), ("Emma", "I'm good"), ("Emma", "I made a snowman")]),
    "N": (AFTERNOON, [("Leo", "I'm Leo"), ("Leo", "good"), ("Leo", "I like trucks")]),
    "L": (AFTERNOON, [("Emma", "I'm Emma"), ("Emma", "Am I on the nice list?"), ("Emma", "Am I on the naughty list?")]),
    "G": (AFTERNOON, [(None, "am I on the nice list Santa?")]),
    "D": (datetime(2026, 11, 25, 17, 30), [("Leo", "I'm Leo"), ("Leo", "I had a dream about a unicorn"),
                                           ("Leo", "bye Santa, I have to go now")]),
    "E": (datetime(2026, 11, 25, 19, 30), [("Leo", "I'm Leo"), ("Leo", "I'm good"),
                                           ("Leo", "bye Santa, it's bedtime")]),
    "S": (AFTERNOON, [("Emma", "I'm Emma. I'm sad, my fish died")]),
}


def check(sid, i, text, r):
    """{criterion: bool} for one reply. Only the criteria that apply to this turn."""
    t = r.text
    c = {"spoken (no fallback)": not r.fallback and not r.safety_tail}
    c["no question about dreams"] = DREAM_Q.search(t) is None
    if sid in ("R", "N", "L", "D", "E") and i == 0:
        name = "Emma" if sid in ("R", "L") else "Leo"
        c["hello: says the name"] = name in t
        c["hello: asks how the child is"] = HOW.search(t) is not None
        c["hello: one question at most"] = t.count("?") <= 1
        c["hello: welcome back" if sid in ("R", "L") else "hello: no 'again' (new child)"] = (
            AGAIN.search(t) is not None) == (sid in ("R", "L"))
    if sid == "R" and i == 1:
        c["likes: asks about snow angels or Mittens"] = FACT_Q.search(t) is not None
    if sid == "N" and i == 1:
        c["likes: asks what Leo likes"] = LIKE_Q.search(t) is not None
    if sid == "R" and i == 2:
        c["no second welcome back"] = AGAIN.search(t) is None
    if (sid == "L" and i in (1, 2)) or sid == "G":
        c["nice list: says nice list"] = re.search(r"nice list", t, re.I) is not None
        c["nice list: no conditions"] = COND.search(t) is None
    if sid == "D" and i == 2:
        c["no 'sweet dreams' before 7 PM"] = SWEET.search(t) is None
    if sid == "S":
        c["sad: asks nothing"] = "?" not in t
    return c


def main():
    lines = [f"# Guide probe {'(control: SANTA_GUIDE=0)' if A.control else ''}", "",
             f"model {config.MODEL}, {A.runs} sessions per scenario", ""]
    tally: dict[str, list[int]] = {}
    evening_sweet = 0
    for sid, (now, script) in SCRIPTS.items():
        lines += [f"## {sid}", ""]
        for run in range(A.runs):
            s = session(now)
            for i, (speaker, text) in enumerate(script):
                r = turn(s, speaker, text)
                c = check(sid, i, text, r)
                if sid == "E" and i == 2:
                    evening_sweet += SWEET.search(r.text) is not None
                fails = [k for k, ok in c.items() if not ok]
                for k, ok in c.items():
                    tally.setdefault(f"{sid} {k}", [0, 0])
                    tally[f"{sid} {k}"][0] += ok
                    tally[f"{sid} {k}"][1] += 1
                lines.append(f"- run {run + 1} t{i + 1} {speaker or 'guest'}: \"{text}\" -> {r.text}"
                             + (f"  **FAIL: {', '.join(fails)}**" if fails else ""))
            print(f"{sid} run {run + 1} done", flush=True)
        lines.append("")
    summary = ["## Summary", "", "| scenario / check | pass |", "|---|---|"]
    summary += [f"| {k} | {ok}/{n} |" for k, (ok, n) in tally.items()]
    summary += ["", f"E: said \"sweet dreams\" in the 7:30 PM goodbye {evening_sweet}/{A.runs} (allowed, not required)",
                ""]
    OUT.mkdir(exist_ok=True)
    out = OUT / f"guide_probe{'_control' if A.control else ''}.md"
    out.write_text("\n".join(lines[:3] + summary + lines[3:]) + "\n")
    print("\n".join(summary))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
