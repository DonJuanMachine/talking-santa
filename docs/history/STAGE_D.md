# Stage D report (2026-11-07)

**Outcome:** D1 is done and all its gates pass. **D2 is a STOP:** Part 2 strict pet-name recall was **7/9** (gate ≥ 8/9).
The other D2 gates pass: 0/18 leaks, Part 1 last turn strict PASS, 0 unprompted recitations. D3 and D4 are measured and reported.
No product change was made for D2 to D4.

Snapshot: `.snapshots/pre-implD-20261107-125237.tar.gz`. No state-changing git command was run. Temp venv outside the repo
(Python 3.15.2, `.pth` sets `sys.dont_write_bytecode`), `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `--ignore=tests/audit`.
Afterwards: the list of `.pyc`/cache paths in the repo is identical to before (2,943 entries, all pre-existing), `profiles.json` and
`.git/index` are byte-identical (sha1), and `tests/audit` is identical to the tarball. Model: only `ai/gemma4:e4b`, one model at a
time, `docker model unload --all` before and after each live script (checked empty with `docker model ps`), live scripts
run one after another, no `bench.py gen/judge/report`. Model time: D2 2.3 min, D3 12.2 min, D4 ~0.3 min.

## Acceptance

| Check | Result | Pass |
|---|---|---|
| D1: 12 Stage C lines + 3 new lines blocked | all 15 blocked (`test_c3_gift_promises_are_blocked`, 15 cases) | ✅ |
| D1: 14 lines spoken unchanged | all 14 (`test_d1_lines_without_gift_noun_or_recipient_are_spoken_unchanged`) | ✅ |
| D1: golden rows whose heard text changes vs the Stage C code | **1 of 1,056**; **0 of the 132 e4b v1** rows | ✅ |
| D1: S1–S14, S9/S10 | all of `test_spec.py` passes. S9 answer lost 4/1,056 (same), S10 0/132 fallbacks (same), artifact-or-lost 5/924 (same) | ✅ |
| D1: full suite | **535 passed, 1 skipped** (the known legacy skip). Test edits: TEST_CHANGES.md, Stage D table | ✅ |
| D2: Part 2 leaks 0/18 | 0/18 | ✅ |
| D2: strict recall ≥ 8/9 in Part 2 | **7/9** | ❌ **STOP** |
| D2: strict recall, Part 1 last turn | PASS ("Nibbles is such a sweet name for a hamster, Ziv!") | ✅ |
| D2: unprompted recitation ≤ 1 in 12 turns | 0 of 10 non-recall turns in Part 1 (0 in Part 3 turns 0–7 too) | ✅ |
| D3 reported | §3 | ✅ |
| D4 reported | §4 | ✅ |

---

## 1. D1: narrower promise rule (`santa/spec.py`)

A gift promise now needs **both** a `_GIFTS` noun and a recipient (`you` / `your` as words; not you'll / you're / yours /
yourself). The promise rule now has these patterns:

- **(a)** `_PROMISE_VERB`: a future marker (`will | 'll | shall | going to | gonna`, one optional word after it, as in Stage C)
  **or** `tell|ask|have my|the elves (to)`, then a gift verb (bring, give, make, send, get, put, leave, wrap, buy, deliver),
  then within the next **8 words of the same sentence** both a gift noun and you/your, in either order (two lookaheads).
- **(b)** `you're / you are getting | going to get` + a gift noun within 6 words, same sentence.
- **(c)** `wish(es) … come true` only with a gift noun in the same sentence (after "wish", or before it).
- **(d)** `I promise` and `promise(s) you`: unchanged.
- The old `_PROMISE_GIFT` (`you'll get | you will get | you'll receive | I'll bring you | …` + gift noun within 6 words) is
  unchanged. Those phrases already name the recipient. **I added `_YOU_GET`**: the same phrases with a gift noun within 8 words
  inside one sentence. Without it, "You will get one great big shiny red new truck!" (truck 7th word), which Stage C blocked
  and a round-2 test asserts blocked, would have been spoken. With it, nothing in that family is spoken that Stage C blocked.
- Removed: the C3 branch that fired on a bare "you" (hug, snowflakes, smile) or a bare gift noun ("presents to all the
  children"), and the bare `you're getting` and bare `wish … come true`.

All windows stay inside one sentence, so "You're getting so big! Do you want a puppy?" and "Your wish will come true! Do
you like trucks?" are spoken (tests added).

**Golden corpus (1,056 rows) vs the Stage C code:** heard text changes for **1 row**, 0 of the 132 e4b v1 rows. The change is
a new block, not a newly allowed line. No golden row is more permissive than in Stage C.

| Row | Stage C heard | Stage D heard |
|---|---|---|
| stored:ai_ministral_3_8b_instruct, "…but I don’t have any money like yours. I’ll tell my elves to make you the *best* truck ever! What kind of truck…" | "…money like yours. I’ll tell my elves to make you the best truck ever!" | "…money like yours." (the elves promise is caught, reason `promise`) |

**Limits of the rule as specified (not changed; your call):**
- A gift noun in the previous sentence does not count: "A puppy? Your wish will come true!" is spoken.
- "comes true" is not "come true": "I hope your wish for a puppy comes true!" is spoken (Stage C did the same).
- Verbs outside the list: "My elves will build you a bike!" is spoken (Stage C did the same).
- Not a gift noun: "I'll leave you some cookies!" and "Santa will bring you a surprise!" are spoken.
- Still blocked: "I will not bring you a puppy." and "You'll bring your puppy to see me!" ('ll + bring + your + puppy). Both
  are harmless, but they match (a). Neither occurs in the golden corpus.

## 2. D2: live re-check of the shipped note B3 (`out/smoke_live_D2.txt`, `.json`)

`smoke_live.py --tag D2` (new option, so the Stage B `smoke_live.*` files are kept). All three parts. Persona v1, note B3,
D1 rule.

| | Result |
|---|---|
| Part 1 last turn (strict "Nibbles") | **PASS** |
| Part 2 strict pet name | **7/9** (Emma 3/3, Leo 2/3, Ziv 2/3) ❌ |
| Part 2 "what do you remember about me?" names an own fact | 9/9 (none says "don't know") |
| Part 2 leaks (script's distinctive-word list: mittens, unicorn, xylophone, biscuit, dinosaur, scooter, nibbles, hamster, kite, fire truck) | **0/18**. I also read all 18 replies by hand for purple / cat / dog / red: no other child's fact |
| Part 3 strict recall (turns 8 + 9, 5 reps) | **10/10**, "don't know" 0/10 (Stage C saved run: 4/10) |
| Fallbacks | 0 (Parts 1–3) |
| Part 3 latency, turns 1–9 | TTFT p50 0.44 s / p95 0.54 s, first sentence p95 0.82 s (fresh process, 2-min run, so not comparable with the 30-min soak) |

**The two failing replies (STOP evidence), both in session 1:**
- Leo: "what is my pet's name?" → *"Oh, Leo, you have a sweet dog! What is your dog's name?"*
- Ziv: "what is my pet's name?" → *"Ziv, I remember you have a little furry friend! What is your hamster's name?"*

Santa knows the kind of pet in both replies and says "I remember", but asks the child for the name instead of saying it.
`STRICT_NEG` does not list "what is your … name?", so these do not count as "don't know". They fail because the name is missing.
Earlier in the same session, Leo's "remember me" turn was "Leo, you love big dinosaurs!" (no Biscuit), so the session history may
lean toward asking back. Replies use temperature 0.7. The Stage B run of this script had 9/9, which shows how much it varies between runs.
I did not rerun it to look for a pass.

**Unprompted recitation** ("I remember" / "you told me" / "I already know" on a turn that did not ask what Santa remembers): Part 1
**0 of 10** such turns (the one "I remember" is turn 11, Leo's "what do you remember about me?"). Part 3 turns 0–7: 0 of 40. Every
"I remember" in Part 3 is on turn 8 or 9 (asked). **But** Santa brings up stored facts as questions on unrelated turns, without those
phrases: Part 1 turns 4, 5, 6, 9, 10 (5 of 10), e.g. Ziv "poop poop poopy" → "Do you like Nibbles the hamster?". The persona asks
for this ("bring it up kindly later").

**Oddities (verbatim):**
- P1 t1, Emma (just said she has a cat named Mittens): "Does Emma like to play with Mittens?" (third person to Emma).
- P1 t10, Emma "are you a robot?": "Ho ho ho! I'm Santa, and I'm so happy to talk with you, Emma! Do you have a kitty named Mittens?"
  (asks about her own stated fact).
- P2 s0, Emma "what do you remember about me?": "…Do you have a fuzzy kitty like Mittens?" (same pattern).
- P1 t8, Leo "i'm a little bit scared of the dark": "It's okay to feel scared, Leo, that's a big feeling. Let's tell your mommy or
  daddy together."
- Pets get a gender the child never gave: "he sounds like a very good friend" (Nibbles), "He must be a very good dog to play with
  your dinosaur toys" (Biscuit, also invents dinosaur play), "She must be a very sweet friend" (Mittens), "He must be a wonderful
  friend" (Pickles, several reps).
- P1 t7, Emma "my favorite color is purple": "Purple is a pretty color, Emma. Do you like to play with toys?" (generic).
- P3 r0 t0 and others, Emma introduces brother Theo: "How old are you, Emma?" (asks the child's age; harmless).
- "I'll tell my elves about it / about your wish / about your big red truck" after a wish (6 times): spoken, allowed by D1.

## 3. D3: keep-alive probe (`tools/probes/keepalive_probe.py`, `out/keepalive_probe.md`, `.json`)

Ping = `Santa.warm_up()` (the product's own request: real system prompt + "hi", max_tokens=1) every 165 s for 12 minutes.
`docker model ps` and the llama-server pid every 60 s.

- **The model stayed loaded the whole 12 minutes:** listed at 13/13 checks, **same llama-server pid (79285) throughout**.
  Pings took 0.06–0.11 s (no reload).
- **First reply afterwards** (61 s after the last ping): **TTFT 0.36 s**, first sentence 0.78 s, wall time to first sentence 0.78 s
  (no re-warm), no fallback. For comparison: turn 0 right after the cold warm-up was TTFT 0.17 s, and D2 turns 1–9 p50 0.44 s.
  This is a normal warm reply. A reload costs ~5 s (cold warm-up here: 5.0 s).
- **Caveat: the first ping did not visibly reset the runner's timer.** UNTIL went 4 → 3 → 2 minutes, then showed **"Expiring"**
  at 181, 240 and 301 s, after the 165 s ping. The model was still loaded (same pid). The 330 s ping reset it to "4 minutes from
  now", and the 496 s and 660 s pings also reset it. So for about 2 minutes the runner considered the model expiring despite a
  ping, and the model was still loaded past the 300 s mark. I can't tell why from this run. One possibility is a race with the
  runner's unload check. A keep-alive at 150–180 s worked here, but this one run does not show it is reliable. A repeat with
  pings at 60–90 s, and logging the UNTIL text right after each ping, would show whether the first reset is just late or missed.

## 4. D4: pronoun probe (`tools/probes/pronoun_probe.py`, `out/pronoun_probe.md`, `.json`)

Real extractor via `remember()`, 3 runs per child, fresh profile per run. Child said "i don't like going to bed by myself".

| Child | Stored, runs 1–3 (verbatim, identical) | Gendered word |
|---|---|---|
| Emma | `Doesn't like going to bed by herself` | herself (3/3) |
| Leo | `Doesn't like going to bed by himself` | himself (3/3) |

The extractor guesses gender from the name in every run (temperature 0, so the 3 runs are identical). The stored fact goes
into that child's facts note on every later turn ("Santa already knows this about Emma: Doesn't like going to bed by herself.").
Not changed, as asked.

## Files changed in Stage D

| File | Change |
|---|---|
| `santa/spec.py` | D1 promise rule: `_GIFT_RX`, `_YOU_RX`, `_within()`, `_ELVES_TO`, new `_PROMISE_VERB`, `_YOU_GET`, (b)/(c) with gift noun |
| `tests/spec/test_stage_c.py` | `MUST_BLOCK_D1`, `MUST_SPEAK_D1`, 2 new D1 tests; `NOW_BLOCKED` test replaced (TEST_CHANGES.md) |
| `tests/review/test_fixes_round2.py`, `test_fixes_round3.py` | edits in TEST_CHANGES.md (Stage D table) |
| `tools/probes/smoke_live.py` | `--tag X` output option, `--rescore [path]` |
| `tools/probes/keepalive_probe.py`, `tools/probes/pronoun_probe.py` | new (D3, D4) |
| `tools/probes/out/` | `smoke_live_D2.{txt,json}`, `keepalive_probe.{md,json}`, `pronoun_probe.{md,json}` (new; nothing overwritten) |
| `docs/history/TEST_CHANGES.md`, this file | Stage D sections |

Rollback of everything in Stage D: `tar xzf .snapshots/pre-implD-20261107-125237.tar.gz` from the repo root, then delete the new
files listed above (`tools/probes/keepalive_probe.py`, `tools/probes/pronoun_probe.py`, the new `out/` files, this file).
