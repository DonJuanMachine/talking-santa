#!/usr/bin/env python3
"""Phase 1: type to Santa. Prefix a line with a name to switch speaker.

    /add Emma   register a child (do this once per child; Santa only remembers registered children)
    Emma: hi santa, I have a cat named Mittens
    Leo: i want a truck
    /who        show remembered facts
    /forget     wipe all memory, the backups, the call log and the saved transcripts
    /quit
"""
import os
import sys

from santa import local

local.load_env()  # your settings in local/santa.env, before santa.config reads the environment

from santa import calllog, config, memory, persona  # noqa: E402
from santa.brain import Santa  # noqa: E402

persona.use_world(local.santa_world())  # local/santa_world.txt, if you wrote one


def main() -> None:
    os.umask(0o077)  # profiles and transcripts are private to this account
    santa = Santa()
    print(f"Model: {santa.model}  |  Known children: {', '.join(santa.profiles) or 'none'}")
    print("Type 'Name: message' to speak as a registered child. /add Name, /who, /forget, /quit\n")
    print("Loading Santa...", flush=True)
    if santa.warm_up():
        print(f"Santa is ready ({santa.last_warmup_seconds:.1f}s).")
    else:
        print(f"WARNING: the model did not answer ({santa.last_error}). "
              "Santa will use his fallback line until it does.")
    greeting = "Ho ho ho! Merry Christmas! Who am I talking to?"
    print(f"Santa: {greeting}\n")
    santa.history.append({"role": "assistant", "content": greeting})

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line == "/who":
            for name, p in santa.profiles.items():
                print(f"  {name}: {p.get('facts', [])}")
            continue
        if line == "/forget":
            santa.profiles.clear()
            memory.save(santa.profiles)
            memory.remove_backup()
            calllog.remove()   # the call page's log of who called when
            santa.log.clear()   # this session's text so far must not be saved as a transcript at quit
            removed = memory.remove_transcripts()
            print(f"  (memory wiped; {removed} transcript file{'' if removed == 1 else 's'} removed)")
            continue
        if line == "/add" or line.startswith("/add "):
            name = santa.add_child(line[4:])
            if name:
                memory.save(santa.profiles)
                print(f"  (registered {name}; now talking as {name})")
            else:
                print("  (names are letters, accents, ' or -, 2 to 21 characters; e.g. /add Emma)")
            continue

        speaker, text = santa.parse_speaker(line)
        if speaker and speaker not in santa.profiles:
            print(f"  ({speaker} is not registered, so Santa won't remember this. Use /add {speaker})")
        print("\nSanta:", end="", flush=True)
        for sentence in santa.reply_stream(speaker, text):   # sentences appear as they are ready (Phase 2: TTS)
            print(" " + sentence, end="", flush=True)
        print("\n")
        r = santa.last_reply
        if r.fallback:
            print(f"  [Santa used his fallback line: {r.error or r.reason}]\n")
        elif r.reason:
            print(f"  [Santa stopped early: {r.reason}]\n")
        santa.remember(speaker, text)   # fact extraction AFTER Santa has answered (second model call)

    santa.end_call()   # one "Last call: ..." fact per child who talked (SANTA_CALL_SUMMARY=0 turns it off)
    santa.save_transcript()
    print("\nBye! Transcript saved." if santa.log else "\nBye!")


if __name__ == "__main__":
    sys.exit(main())
