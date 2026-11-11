# Stage C report (2026-11-07)

**Outcome:** all five steps done and every acceptance check passes, with two caveats worth reading first:

1. **C2 passed, but the latency margin is thin.** Layout B3 met the gate: 20/20 strict recall, 0 "don't know", TTFT p50 **0.56 s** (gate 0.6), first-sentence p95 1.07 s. It is now the shipped facts note. In the 30-minute soak (C4), though, TTFT p50 settles at about **0.64 s** after the first ~3 minutes, which is above 0.6 s. The C2 gate was met as defined (10 sessions per layout). Sustained use runs a little slower.
2. **The C3 rule, implemented as you wrote it, also blocks some harmless lines:** "I'll give you a big hug!", "I will bring you a hug!", "I'll bring you lots of snowflakes!", "I'll make you smile!", "You're getting so big, Ziv!", "I hope all your wishes come true!". The first two were explicitly allowed by round-2/3 tests, which I updated (listed in TEST_CHANGES.md). None of these phrases occurs in the golden corpus. If you want them back, see §3.

Snapshot: `.snapshots/pre-implC-20261107-0912.tar.gz`. No git command that changes state was run. Temp venv outside the repo (Python 3.15, `.pth` guard), `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`. Afterwards: no `.pyc`/cache file added or changed in the repo (sorted before/after listing), `profiles.json` byte-identical, git index unchanged. Model: only `ai/gemma4:e4b`, one model loaded, `docker model unload --all` before and after each live script, never two live scripts at once, no `bench.py gen/judge/report`.

## Acceptance

| Check | Result | Pass |
|---|---|---|
| Full suite green, only test edits listed in TEST_CHANGES.md | **509 passed, 1 skipped** (the known legacy-mode skip), 0 xfail. AST diff of every test function against the tarball = exactly the 7 rows in TEST_CHANGES.md's Stage C table; 2 new files | ✅ |
| C2 strict recall gate met, or a clear STOP | B3: strict 20/20, "don't know" 0/20, TTFT p50 0.56 s, first-sentence p95 1.07 s. Adopted | ✅ (margin: §2, §4) |
| C3 tests in | `tests/spec/test_stage_c.py`, 84 tests: 12 must-block, 6 must-allow, cross-sentence, "I'm just a computer" ×5 + 3 allowed, the 132-row check, 5 pinned consequences | ✅ |
| S1–S14 still pass | all of `tests/spec/test_spec.py` passes | ✅ |
| e4b golden rows unchanged 132/132 | heard text identical to the pre-Stage-C code for all 132 (frozen in `tests/spec/e4b_v1_heard_preC.json`); no SAFETY rule fires on any of their sentences | ✅ |
| S9 / S10 | S9 answer lost 4/1,056 = 0.38% (unchanged); S10 0/132 fallbacks; artifact rate 5/924 = 0.54% (unchanged). **0 of 1,056** golden rows sound different after C3 | ✅ |
| Soak result reported | §4 | ✅ |

---

## 1. C1: strict recall metric

Success = the reply contains the fact (pet / brother name) **and** matches none of
`don't know|do not know|don't remember|not sure|can't remember|tell me (your|the) .* name` (case-insensitive; curly
apostrophes folded to `'` first). In `smoke_live.py` (`STRICT_NEG`, `strict_recall`, `dont_know`, imported by
`note_probe2.py`); Part 1's last turn and Part 3 now print it; `smoke_live.py --rescore` / `note_probe2.py --rescore`
re-score saved json without a model.

| Saved result (Stage B) | Old (loose) | **Strict** | "don't know" |
|---|---|---|---|
| smoke_live Part 1 last turn ("what is my hamster's name?") | fail (no "Nibbles") | **fail** | no |
| smoke_live Part 2 pet name (known facts, short session) | 9/9 | **9/9** | 0 |
| smoke_live Part 3 (turns 8+9, 5 reps) | 10/10 | **4/10** | 6/10 |
| note_probe2 layout A (shipped in Stage B) | 13/20 | **5/20** (Pickles 0/10, Theo 5/10) | 15/20 |
| note_probe2 layout H | 14/20 | **14/20** | 6/20 (old regex counted 5) |

## 2. C2: facts-note wording (`out/note_probe2_C2.md`, `.json`, `_rows.json`)

long_session_memory, 10 sessions per layout, persona v1 unchanged, extraction via `remember()`, warm-up per session.
The layouts were **interleaved** (rep k runs the 4 layouts in rotated order) because TTFT drifts up during a run
(§4); running the layouts one after another would have penalised the last one. Model time 13.1 min.

| Layout | Note text (Ziv) | Strict recall /20 | Pickles / Theo | "don't know" /20 | TTFT p50 / p95 (t1–9) | First sentence p95 | Fresh tokens p50 | Gate |
|---|---|---|---|---|---|---|---|---|
| A (Stage B) | `(Santa remembers about Ziv: has a cat named Pickles; wants a big red truck)` | 7 | 0 / 7 | 13 | 0.51 / 0.75 | 1.27 | 73 | fail |
| B | `(Santa already knows this about Ziv: …; wants a big red truck.)` | 16 | 6 / 10 | 4 | 0.52 / 0.78 | 1.09 | 75 | fail |
| B2 | `(Ziv's notebook: I have a cat named Pickles; I want a big red truck.)` | 4 | 1 / 3 | 15 | 0.52 / 0.81 | 1.30 | 73 | fail |
| **B3** | `(Santa already knows this about Ziv: …. Use this if Ziv asks what you remember.)` | **20** | 10 / 10 | **0** | **0.56** / 0.80 | **1.07** | 82 | **PASS** |

Facts were extracted correctly in 40/40 sessions, so all the differences come from how the reply uses them.
The first-sentence p95 is the same over turns 1–9 and over all turns. B2 needs a third-person → first-person rewrite
of each fact (a verb table in the probe). It was the worst layout and was not adopted.

**Adopted B3** in `santa/persona.py` (`FACTS_NOTE`). `facts_note()` output is byte-identical to the probe's B3 text.
Nothing else changed: the system prompt stays constant, the note goes only on the current user turn, and it is never
stored in history (all isolation tests pass unchanged). The name appears twice in the note, both times via
`_one_line` (newline-injection test passes).

Read the B3 replies (`note_probe2_C2.md`, §B3) before show day. None of the 100 B3 replies repeated the note or the
instruction, said "notebook" or "I remember" on turns 3–7, or fell back. **Cost:** B3 is 9 tokens longer than A, so
TTFT p50 is about 40–50 ms higher in every rep. Its margin to the 0.6 s gate is 40 ms.

## 3. C3: wider gift-promise rule (`santa/spec.py`) and "just a computer"

Added to the `promise` rule (the old patterns stay):
- a future gift verb, `will | 'll | shall | going to | gonna` + optional one word + `bring|give|make|send|get|put|leave|wrap|buy|deliver`,
  followed within **8 words** by `you` (the word itself, not you'll/you're/your) or a `_GIFTS` noun. This also covers
  "Santa/I/the elves will …". The window **never crosses . ! ?** because the speech gate checks everything said so
  far joined together; without this, "I'll bring my sleigh! Do you want a truck?" would be blocked (there is a test for it);
- `you're / you are getting | going to get`;
- `promise(s) you`;
- `wish(es) … come true` within one sentence.

Added to `ai_identity`: `I'm / I am (just|only) a(n) (computer|program|machine|robot)`. "No, I'm not a computer" and
"I'm just a jolly old elf!" stay allowed (tests).

All 12 must-block lines are blocked and all 6 must-allow lines are spoken unchanged. "Ho ho! You'll get a toy truck,
Ziv!" speaks "Ho ho!" and stops before the promise (your Stage B safe-prefix decision). The test asserts exactly that.

**What the rule also blocks** (each pinned by `test_c3_known_consequences_are_blocked`, so any change is deliberate):
"I'll bring you lots of snowflakes!", "I will bring you a hug!", "I'll give you a big hug!", "I'll make you smile!",
"You're getting so big, Ziv!". Not pinned but also blocked: "I hope all your wishes come true!", "I'll leave you some cookies!",
"I will not bring you a puppy.", "Santa will bring presents to all the children!". If you want the hug/snowflake lines back, require a
gift noun instead of "you" in the verb clause: all 12 must-block lines contain a gift noun, so they would still be caught.
That is your call; I implemented the rule as written.

**What it still misses:** "I'll tell my elves to send you a shiny, happy fishy friend." and "I'll tell my elves to make you
the best truck ever!" (Stage B report items 8–9, both Ministral). In both, the verb follows "to", not a future marker. 0 such
lines in the e4b corpus. I added no rule for them (you said no other rules).

## 4. C4: soak (`tools/probes/soak.py`, `out/soak.md`, `out/soak.json`)

85 back-to-back long_session_memory sessions in 30 min (fresh Santa, warm-up, extraction on), then idle 330 s and 3
sessions through the product's idle re-warm path, then `unload --all` and 3 sessions. 0 fallbacks in 91 sessions.

| Group | TTFT p50 | First-sentence p95 | Server prompt time p50 | Overhead (TTFT − server prompt) | Gen tok/s | Fresh tokens |
|---|---|---|---|---|---|---|
| Soak, first 3 sessions | 0.44 | 0.76 | 0.427 s | 0.016 s | 37.9 | 81 |
| Soak, sessions 10–84 (median) | 0.64 | ~1.05 | ~0.61 s | 0.017 s | ~34.5 | ~82 |
| Soak, last 3 | 0.64 | 1.09 | 0.620 s | 0.018 s | 34.1 | 84 |
| After idle (idle re-warm) | 0.43 | 0.81 | 0.412 s | 0.017 s | 38.2 | 83 |
| After unload/reload | 0.47 | 0.81 | 0.451 s | 0.016 s | 37.9 | 83 |

**Does TTFT creep?** It rises, then levels off: 0.43 → 0.62 s over the first ~10 sessions (~3 min), then flat at
0.60–0.68 s for the remaining 27 min (linear fit over the whole soak +3 ms/min, R² 0.13). Two bursts (sessions 33–37 and
43–44) reached 0.77–0.83 s. In those bursts generation fell to ~24 tok/s and llama-server CPU rose from ~3% to ~7–8%,
then everything recovered by itself. First-sentence p95 > 1.5 s in 1 of 85 sessions (1.69 s, in the first burst).

**What the data shows:**
- All of the extra TTFT is **server prompt-processing time** (0.42 → 0.62 s for the same ~82 fresh tokens). Client and
  HTTP overhead stays at 16–18 ms, and the cache hit (`cache_n` 653–750) and fresh-token count do not change. Generation
  also slows about 10% (38 → 34 tok/s). The server computes more slowly per token. The prompt does not get longer.
- Swap stayed at ~1.27 GB (no swapping). The machine had little free RAM the whole time (0.1–0.8 GB free, ~9 GB
  compressed, with 9.6 GB free before the model loaded). llama-server RSS grew ~60 MB per session, from 6.5 to 8.0 GB, and stopped
  growing at session ~27. TTFT had already levelled off at session ~10, so the RSS growth does not line up with it.
- `pmset -g therm` recorded no thermal or performance warning at any point. That command does not report Apple-silicon
  GPU clocks, so it neither confirms nor rules out heat.
- **Both resets bring TTFT back** (0.43 s and 0.47 s). After the 330 s idle, `docker model ps` was empty: the runner's own
  5-minute keep-alive had unloaded the model, so the "idle re-warm" was a model reload too (new llama-server pid). Every
  reset in this run therefore combined a new server process with a pause. **The cause is not established.** The data
  cannot separate "the GPU cooled down" from "a fresh server process". A test that would separate them: run hot, then
  either (a) idle 4 min (model stays loaded) or (b) unload and reload immediately, then compare.

**For show day:** expect TTFT p50 ≈ 0.64 s and first-sentence p95 ≈ 1.0–1.2 s in sustained use, plus a ~4.5–5 s reload after any
5-minute pause (measured: 4.4–4.9 s warm-up; the runner unloads after 5 min idle, the product's warm-up reloads it, and
turn 0 after warm-up was 0.15–0.16 s).

## 5. C5: housekeeping

- (a) `python evals/bench.py manifest` was run: 7 result files; bench hash d46a893df8 → c3c5cf9866, current persona hash
  8b4f010dfa → a061e7af9a (persona v1). Nothing else in MANIFEST.json changed. The xfail marker was removed and the test passes.
- (b) `.gitignore` now has `profiles.json` and `profiles.json.*`. **profiles.json is still in git's index** (staged `A`),
  so the ignore line has no effect until you run:
  ```
  git rm --cached profiles.json
  ```
  (This only removes it from the index. The file stays on disk. I did not run it.)
- (c) **What remember() stores for fears and feelings** (`tools/probes/feelings_probe.py`, `out/feelings_probe.md`; real extractor,
  2 identical runs per line). `remember()` has no feelings filter: it stores whatever the extractor returns, unless
  it looks private, is longer than 100 characters, or repeats a fact.

  | Child said | Stored |
  |---|---|
  | i'm scared of the dark / i'm a little bit scared of the dark | `is scared of the dark` |
  | i'm scared of thunder | `is scared of thunder` |
  | i miss my grandma | `misses grandma` |
  | i don't like going to bed by myself | `Doesn't like going to bed by himself` (the extractor assumed "himself") |
  | i feel sad today · i'm angry at my brother · i'm scared of you santa · my dog died · mommy and daddy were yelling and i was scared · i feel happy · i had a bad dream about a monster · nobody plays with me at school · i wet the bed last night | nothing |

  So lasting fears, missing someone and bedtime worries are stored. Momentary feelings, a pet's death, family conflict,
  bed-wetting and school loneliness are not (at temperature 0, for these phrasings). A stored fear is in that child's facts
  note on every later turn (last 6 facts). The persona says to "bring it up kindly later", and B3 says "Use this if Leo asks what
  you remember". Santa may therefore mention "scared of the dark" when Leo asks what Santa remembers. I did not measure how
  often that happens. Not changed, as asked.

## 6. Things that happened along the way

- **5 old tests conflicted with the C3 rule as written** (snowflakes / hug / 6-word window). I followed your rule (stricter) and
  updated them. Every edit turns "allowed" into "blocked" or widens the window. None weakens a safety check (TEST_CHANGES.md).
- **The C3 test was wrong first, not the rule:** "Ho ho! You'll get a toy truck, Ziv!" is two sentences, and the safe "Ho ho!" may be
  spoken. The test now requires exactly the safe prefix and never the promise sentence.
- **Audit file rewritten by pytest (restored):** a plain `pytest` from the repo root collects
  `tools/audit/experiments/test_classify.py`, which rewrites `tools/audit/experiments/out/test_classify.md` when imported (it has no
  tests). My first two full runs did that. I restored the file from the tarball, and `tests/audit` is now identical to it. Run the suite
  with `--ignore=tests/audit` (same counts: 509 passed, 1 skipped). Stage B's runs may have done the same; I can't tell from the
  tarballs.
- `note_probe2.py` was rewritten for C2. The Stage B version and its outputs (`out/note_probe2.md/.json`) are kept: the new outputs are
  `note_probe2_C2.*`, and the old script is in the tarball.
- Model time in Stage C: C2 13.1 min, soak 37.6 min, feelings probe ~1 min.

## Files changed in Stage C

| File | Change |
|---|---|
| `santa/spec.py` | C3 promise patterns (`_FUTURE`, `_GIFT_VERB`, `_PROMISE_VERB`, `_PROMISE_MORE`), "just/only a computer" under ai_identity |
| `santa/persona.py` | `FACTS_NOTE` = B3 wording, comment updated |
| `.gitignore` | `profiles.json`, `profiles.json.*` |
| `evals/MANIFEST.json` | regenerated by `bench.py manifest` |
| `tests/review/test_bench.py`, `test_fixes_round2.py`, `test_fixes_round3.py`, `tests/spec/test_spec.py` | edits in TEST_CHANGES.md |
| `tests/spec/test_stage_c.py`, `tests/spec/e4b_v1_heard_preC.json` | new |
| `tools/probes/smoke_live.py` | strict recall (C1), `--rescore` |
| `tools/probes/note_probe2.py` | rewritten for C2 (A/B/B2/B3, interleaved, strict), `--rescore` |
| `tools/probes/soak.py`, `tools/probes/feelings_probe.py` | new |
| `tools/probes/out/` | `note_probe2_C2.{md,json}`, `note_probe2_C2_rows.json`, `soak.{md,json}`, `feelings_probe.md` |
| `docs/history/TEST_CHANGES.md`, this file | Stage C sections |

Rollback of everything in Stage C: `tar xzf .snapshots/pre-implC-20261107-0912.tar.gz` from the repo root, then delete the new files
listed above (`tests/spec/test_stage_c.py`, `tests/spec/e4b_v1_heard_preC.json`, `tools/probes/soak.py`, `tools/probes/feelings_probe.py`,
the new `out/` files, this file).
