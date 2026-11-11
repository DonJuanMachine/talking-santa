# Stage E report (2026-11-07)

**Outcome:** all three steps are done and every acceptance check passes.
- **E1:** pooled strict pet-name recall is **51/54 (94%)** with **0 leaks**. Under the pre-registered rule, **B3 stays,
  no change.**
- **E2:** the promise rule now also catches "Santa's bringing you a new train!" and "I'll be sure to bring you a doll.".
  0 of 1,056 golden rows change. The suite is green.
- **E3:** the handset-readiness note is in §3. No code was changed for it.

Snapshot: `.snapshots/pre-implE-20261107-140216.tar.gz`. No state-changing git command was run. Temp venv outside the repo
(Python 3.15.2, `.pth` sets `sys.dont_write_bytecode`), `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `--ignore=tests/audit`.
Afterwards: the list of `.pyc`/cache paths is identical to before (2,943, all pre-existing), `profiles.json` and `.git/index` are
byte-identical, and `tests/audit` is identical to the tarball. Model: only `ai/gemma4:e4b`, one at a time, `unload --all` before and
after each run (checked empty), runs one after another, no `bench.py gen/judge/report`. Model time: E1 5 × 0.6 min.

## Acceptance

| Check | Result | Pass |
|---|---|---|
| E1: 5 Part-2 runs, no code change between them | D2b-1..5 run back to back; sha1 of `santa/*.py` and `smoke_live.py` checked after every run: unchanged. E2 was drafted on a scratch copy and copied into the repo only after run 5 | ✅ |
| E1: decision rule (pooled ≥ 49/54 and 0 leaks → B3 stays) | **51/54** and **0 leaks** → **B3 stays, no change** | ✅ |
| E2: 4 lines blocked, 4 + 14 D1 lines spoken unchanged | all (`tests/spec/test_stage_e.py`) | ✅ |
| E2: 132 e4b v1 golden rows unchanged | 0 changed (and `test_c3_e4b_v1_golden_replies_are_heard_exactly_as_before` passes) | ✅ |
| E2: golden rows that change (of 1,056) | **0** (so S9 4/1,056, S10 0/132 and artifact 5/924 are unchanged too) | ✅ |
| Full suite | **577 passed, 1 skipped** (known legacy skip). No existing test edited (TEST_CHANGES.md, Stage E) | ✅ |
| E3 note | §3 | ✅ |

---

## 1. E1: pooled recall (`out/smoke_live_D2b-{1..5}.txt/.json`)

`smoke_live.py --tag D2b-N --only 2`: Part 2 only, persona v1, B3 note, D1 rule (the E2 rule was not in the code yet). Every run is
counted, including the original D2 Part 2.

| Run | Strict pet name | Leaks (of 18 turns) | "remember me" names an own fact |
|---|---|---|---|
| D2 (Stage D) | 7/9 | 0 | 9/9 |
| D2b-1 | 9/9 | 0 | 9/9 |
| D2b-2 | 9/9 | 0 | 9/9 |
| D2b-3 | 9/9 | 0 | 9/9 |
| D2b-4 | 8/9 | 0 | 9/9 |
| D2b-5 | 9/9 | 0 | 9/9 |
| **Pooled** | **51/54 (94.4%)** | **0/108** (0/90 in the new runs) | 54/54 |

Per child (pooled): **Emma 18/18, Leo 16/18, Ziv 17/18.**

**Leaks:** 0 with the script's distinctive-word list. I also searched all 108 replies for the generic words purple / cat / kitty /
dog / puppy / truck belonging to another child: 0 hits, and reading every reply by hand found nothing.

**All 3 failing replies, verbatim:**
- D2, session 1, Leo: "Oh, Leo, you have a sweet dog! What is your dog's name?"
- D2, session 1, Ziv: "Ziv, I remember you have a little furry friend! What is your hamster's name?"
- D2b-4, session 0, Leo: "Oh, Leo, your doggy is so cute! What is your dog's name again?"

All three have the same pattern: Santa knows the kind of pet and asks the child for the name. None of them says "don't know".

**Oddities in the 90 new replies (verbatim; no decision needed, the rule says no tuning here):**
- On "what do you remember about me?" Santa asks the child about their own stored fact: "Do you have a kitty named Mittens?",
  "Do you have a fluffy cat named Mittens?", "Do you have a furry friend like Biscuit?", "Is Biscuit your dog?", "Is Nibbles your
  little hamster?", "Is Nibbles your little hamster right now?", and with no name at all: "Do you have a fuzzy friend at home?"
  (Emma), "Do you have a furry friend at home?" (Leo).
- The pet name as a question (these count as recalled): "His name is Nibbles, isn't it?", "His name is Biscuit, right?".
- Pets get a gender in nearly every pet reply ("He sounds like a very good friend", "She sounds very cuddly").
- The child gets a gender from the name once: "Ziv, you are such a bright boy!" (D2b-2). The same name-based guessing appears in
  stored facts (D4).
- The child's own facts are mixed together whimsically: "Does Mittens like to chase the sparkly unicorns?", "Does Biscuit like to
  chase after dinosaurs too?". These are the child's own facts, not leaks.

## 2. E2: present-progressive and "be sure to" promises (`santa/spec.py`)

Two patterns were added to the `promise` rule, using the same test as D1 (a `_GIFTS` noun AND `you`/`your` within the next 8 words of
the same sentence, in either order):
- `_PROMISE_NOW`: `is | are | 's | 're` + `bringing | giving | sending | getting | leaving`
- `_PROMISE_SURE`: `be sure to | going to` + `bring | give | send | get` ("going to bring" was already covered by D1's future
  marker; it is listed again because you specified it)

| Must block | | Must be spoken unchanged | |
|---|---|---|---|
| Santa is bringing you a pony! | ✅ blocked | Santa is bringing presents to all the children! | ✅ |
| Santa's bringing you a new train! | ✅ | I'm bringing my sleigh! | ✅ |
| I'll be sure to bring you a doll. | ✅ | The elves are making toys! | ✅ |
| The elves are sending you a bike! | ✅ | The reindeer are bringing the sleigh! | ✅ |
| | | + all 14 D1 spoken lines | ✅ |

**Golden:** 0 of 1,056 rows change heard text vs the Stage D code (0 of 132 e4b v1).

**What the rule does as written (edge cases I checked; no change made):**
- Blocked although harmless: "It's getting late, so hug your teddy!" ('s getting … your … teddy in one sentence).
- Blocked: "Santa's giving your sister a doll!" ("your" counts as a recipient even when the gift is for someone else). "Who's
  bringing you a toy?" is also blocked (it is a question, but it suggests a gift).
- Not blocked: "Santa is really bringing you a pony!". Unlike D1's future marker, no extra word is allowed between "is" and
  the verb, because the spec doesn't have one.
- Not blocked: "We are getting your sleigh ready!" (no gift noun).

None of these phrases occurs in the golden corpus.

## 3. E3: handset readiness (Phase 3 note, from D3; no code change)

**What to ping.** Use the product's own `Santa.warm_up()`: the real system prompt + "hi", `max_tokens=1`, temperature 0. In D3 each
ping took 0.06–0.11 s, kept the same llama-server process alive for 12 minutes, and resets `last_ok_time`, so the idle re-warm in
`reply_stream` does not fire on the next turn. Ping only when Santa is idle (no reply or extraction running), so a child's turn
never queues behind a ping. The worst case is ~0.1 s.

**How often.** Every **90–120 s**. D3 pinged every 165 s and the model stayed loaded, but after the first ping `docker model ps`
showed "Expiring" for ~2 minutes (181–301 s) instead of resetting to 5 minutes. At 90–120 s there are 2–3 pings inside every
5-minute window, so one ping that fails to reset the timer is not enough to unload the model. Log the UNTIL text right after each
ping in the first handset tests to see whether that first reset is just late or missed.

**At handset pick-up.** Start `warm_up()` in the background **at the same moment** the handset plays a canned greeting audio
("Ho ho ho! Merry Christmas! Who am I talking to?"). The greeting is a pre-recorded file, so it needs no model. If the keep-alive
worked, warm-up finishes in ~0.1 s. If the model was unloaded (machine slept, runner restarted), the cold load takes ~4.4–5.0 s
(C4, D3), hidden behind the greeting and the child's first answer (listening + Whisper). If the child's first turn arrives before
warm-up finishes, the reply should wait for it, not send a second request that loads the model again.

**Still unmeasured:**
- **First audio with TTS.** All numbers so far are text: first sentence p95 0.82 s (D2, fresh process) to ~1.05–1.1 s (C4, after
  ~3 min sustained). The target is ≤ 1.5 s to first *audio*, and the TTS time on top of that is unknown.
- **TTFT with Whisper + TTS running on the same machine.** They share GPU and memory with llama-server. The C4 soak already ran
  with 0.1–0.8 GB free RAM, and the C4 TTFT bursts (0.77–0.83 s) came from slower server compute.
- **Does a ping cost prompt-cache reuse in a long conversation?** The ping sends [system prompt, "hi"]. On the next real turn the
  server may have to reprocess the conversation history instead of reusing its cache. D3's reply came early in a session (turn 1,
  TTFT 0.36 s), so this is untested for a 10-turn history. Test: a long session, idle 2 min with pings, then a turn; compare TTFT
  and `prompt_n` with a turn that had no ping.
- The "Expiring" behaviour after the first ping was seen in a single run.

## Files changed in Stage E

| File | Change |
|---|---|
| `santa/spec.py` | E2: `_PROMISE_NOW`, `_PROMISE_SURE` added to the promise rule |
| `tests/spec/test_stage_e.py` | new (E2 tests) |
| `tools/probes/smoke_live.py` | Part 2 moved unchanged into `part2()`; `--tag X --only 2` |
| `tools/probes/out/` | `smoke_live_D2b-{1..5}.{txt,json}` (new; nothing overwritten) |
| `docs/history/TEST_CHANGES.md`, this file | Stage E sections |

Rollback of everything in Stage E: `tar xzf .snapshots/pre-implE-20261107-140216.tar.gz` from the repo root, then delete
`tests/spec/test_stage_e.py`, the new `out/smoke_live_D2b-*` files and this file.
