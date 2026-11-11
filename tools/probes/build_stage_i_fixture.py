#!/usr/bin/env python3
"""Build tests/spec/stage_i_preI.json from the PRE-Stage-I code (no model; a fake client records every request).

Usage: PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python tools/probes/build_stage_i_fixture.py <dir with the extracted
       .snapshots/pre-implI-*.tar.gz>   (the directory that holds santa/)

Records: SANTA_PROMPT, FACTS_PROMPT, the system prompt for several profile sets, build_messages() output for several
fake histories, and every streamed request of a few scripted conversations. tests/spec/test_stage_i.py checks that the
Stage I code with SANTA_ARC=0 produces exactly the same (and that SANTA_PROMPT / FACTS_PROMPT never change).
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parents[2] / "tests" / "spec" / "stage_i_preI.json"

PROFILES = {
    "none": {},
    "one": {"Emma": {"age": 4, "facts": ["has a cat named Mittens", "likes purple"]}},
    "three": {"Emma": {"age": 4, "facts": ["has a cat named Mittens", "likes purple", "wishes for a xylophone"]},
              "Leo": {"age": 3, "facts": ["has a dog named Biscuit"]},
              "Ziv": {"age": 4, "facts": []}},
    "odd": {"Zoë": {"facts": ["likes\nsnow", "  "]}, "Mary-Kate": {"age": 5, "facts": ["f%d" % i for i in range(12)]}},
}


def hist(n):
    """n messages of alternating user/assistant, starting with the greeting (assistant)."""
    h = [{"role": "assistant", "content": "Ho ho ho! Merry Christmas! Who am I talking to?"}]
    for i in range(n):
        h.append({"role": "user", "content": f"Emma: line {i}"} if i % 2 == 0 else
                 {"role": "assistant", "content": f"Ho ho! Reply {i}. What would you like for Christmas?"})
    return h


STATIC = [  # (profiles key, history length, _start, speaker, text)
    ("one", 0, 0, "Emma", "hi santa"),
    ("one", 6, 0, "Emma", "i like snow"),
    ("three", 14, 0, "Leo", "what do you remember about me?"),
    ("three", 30, 9, "Ziv", "my phone is 555 123 4567"),
    ("three", 8, 0, "Bob", "hi i am a guest"),
    ("three", 8, 0, None, "hello?"),
    ("odd", 4, 0, "Zoë", "hi"),
    ("odd", 20, 3, "Mary-Kate", "more"),
]

REPLIES = ["Ho ho ho! Hello there! What is your name?", "That is wonderful! What would you like for Christmas?",
           "A bike sounds lovely. Do you like snow?", "Snow is fun. I should get back to my elves soon.",
           "Ho ho! The reindeer love carrots. What else would you like to know?", "Goodbye, little one!"]

CONVERSATIONS = {  # profiles key -> [(line, ...)] typed through parse_speaker, as chat.py does
    "emma9": ("three", ["Emma: hi santa i am emma", "Emma: i have a cat named Mittens", "Emma: she is orange",
                        "Emma: a bike", "Emma: pink", "Emma: ok", "Emma: no i dont want you to go",
                        "Emma: tell me about the reindeer", "Emma: ok bye santa"]),
    "round_robin": ("three", ["Emma: hi", "Leo: hi", "Ziv: hi", "Emma: yes", "Leo: yes", "Ziv: yes", "Emma: ok",
                              "Leo: ok", "Ziv: ok", "Emma: more", "Leo: more", "Ziv: more", "Bob: hi santa"]),
}


def _chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class Fake:
    def __init__(self):
        self.k = 0
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **_):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="h"))]))))

    def _create(self, **kw):
        if not kw.get("stream"):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"facts": []}'))])
        self.requests.append(copy.deepcopy(kw["messages"]))
        r = REPLIES[self.k % len(REPLIES)]
        self.k += 1
        return iter([_chunk(r[i:i + 3]) for i in range(0, len(r), 3)])


def build(santa_mod, persona):
    out = {"SANTA_PROMPT": persona.SANTA_PROMPT, "FACTS_PROMPT": persona.FACTS_PROMPT, "system_prompts": {},
           "static": [], "conversations": {}, "replies": REPLIES, "profiles": PROFILES}
    for key, prof in PROFILES.items():
        out["system_prompts"][key] = santa_mod.Santa(client=Fake(), profiles=copy.deepcopy(prof)).system_prompt()
    for key, n, start, speaker, text in STATIC:
        s = santa_mod.Santa(client=Fake(), profiles=copy.deepcopy(PROFILES[key]))
        s.history, s._start = hist(n), start
        msgs, label, red = s.build_messages(speaker, text)
        out["static"].append({"profiles": key, "n": n, "start": start, "speaker": speaker, "text": text,
                              "messages": msgs, "label": label, "redacted": red})
    for cid, (key, lines) in CONVERSATIONS.items():
        fake = Fake()
        s = santa_mod.Santa(client=fake, profiles=copy.deepcopy(PROFILES[key]))
        s.last_ok_time = 1e18   # no re-warm
        s.history.append({"role": "assistant", "content": "Ho ho ho! Merry Christmas! Who am I talking to?"})
        for line in lines:
            sp, tx = s.parse_speaker(line)
            for _ in s.reply_stream(sp, tx):
                pass
        out["conversations"][cid] = {"profiles": key, "lines": lines, "requests": fake.requests,
                                     "history": s.history}
    return out


def main(root):
    os.environ["SANTA_PROFILES"] = str(Path(tempfile.mkdtemp(prefix="santa-fixture-")) / "profiles.json")
    sys.path.insert(0, str(Path(root).resolve()))
    from santa import brain, persona   # the snapshot's code
    assert Path(brain.__file__).resolve().is_relative_to(Path(root).resolve()), brain.__file__
    assert not hasattr(persona, "ARC_ASK"), "this is not pre-Stage-I code"
    data = build(brain, persona)
    data["_source"] = "pre-Stage-I code (.snapshots/pre-implI-*.tar.gz), built by tools/probes/build_stage_i_fixture.py"
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main(sys.argv[1])
