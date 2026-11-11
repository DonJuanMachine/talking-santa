# Talking Santa: root-cause audit of the fix rounds

Audit date: 2026-11-05, 06:40–08:00. Read-only on product code, results, snapshots and git.
All scripts and raw outputs are in `tools/audit/experiments/` (outputs in `experiments/out/`).
Tags: **VERIFIED** = I ran it or read it in code/data (file:line or script cited). **INFERRED** = reasoned, not tested.
**UNKNOWN** = needs a live model or a person listening.

---

## Executive summary

**Verdict.** The project keeps going back and forth because one module, `santa/safety.py`, has been asked to
rewrite the model's replies into a good shape: one question, three sentences, keep the real question, avoid
echo questions. Repairing text after the fact cannot do this. Each repair rule turns one visible failure into a
different one that nobody was measuring. Each round then checked only the failure it was asked to fix, with
example tests that pass by construction. Measured on the same 924 stored raw replies, the share of heard replies
with an **artifact or a lost answer went 1.6% → 4.9% → 5.2% → 8.8%** across rounds 1–3, while the full test
suite went from 25 passing tests to 294 [VERIFIED: `out/quality.md`, `out/test_matrix.md`]. The worst current
example: a child says "my goldfish died", and the filter drops every caring sentence. The child hears
*"Oh, Ziv... Do you have another pet you love?"* [VERIFIED: `out/labels60.md` #54].

**Why it keeps happening (structural):**
1. **Style rules and safety rules are enforced by the same mechanism.** Breaking the one-question or
   three-sentence rule is not a safety problem (an adult is present), yet these rules are enforced by rewriting text.
   That rewriting is where all the regressions come from [VERIFIED: §3, §4].
2. **There is no single definition of a valid reply.** It is defined five times (persona, `config`, `sanitize`,
   `check`, `bench.rule_flags`, plus a sixth list in `run_evals.py`). `check()` and `rule_flags()` disagree on
   **20.2%** of raw replies [VERIFIED: `out/rule_drift.md`].
3. **The filter was patched to make up for a persona change that was never measured.** Persona v2 took
   gemma4:e4b from **0/132** replies needing repair (v1) to **34/132**. Rounds 1–3 then compensated in the
   filter. Persona v3, which `santa/persona.py` runs today, has **never been benchmarked** [VERIFIED].
4. **No test said what "good" means.** 203 of 204 test functions check examples, mocks or harness details. The
   only test over real replies checks a single number, the no-question rate ≤ 30%. Round 3 met that number by
   dropping the middle of replies, and that is how the goldfish case happened [VERIFIED: `test_fixes_round3.py:106-117`].
5. **The benchmark cannot see the pipeline it is supposed to measure.** Result files mix two code versions.
   48.4% of stored "heard" answers come from a filter that no longer exists. The judge cache has no hashes.
   `bench_report.md` was written by the code as it was before round 1 [VERIFIED: §7].

**Hypotheses:** H1 partly confirmed (the diagnosis is right, but regeneration is not the remedy; the data
refutes it: a second sample passes only 9–21% of the time after a failure). H2 confirmed. H3 partly confirmed
(only 4 tests broke across rounds; the real problem is that green tests did not detect quality regressions).
H4 confirmed. H5 partly confirmed. H6 confirmed. H7 confirmed. H8 confirmed. Details in the table in §0.

**Root causes you did not name:** (a) style and safety mixed in one mechanism. (b) The filter was tuned to
Ministral's habits: Ministral raw replies are 8–10% clean, Gemma's 74–100%. (c) **Latency is dominated by how
the prompt is built, not by the filter.** On the turns where memory extraction is switched on (as it is in the real app),
e4b's median time-to-first-token is **2.7 s** against 0.3 s without memory. Fact extraction (0.7–2.8 s) also runs
*before* `reply()` returns. The 1.1–1.3 s medians you quoted are mostly single-turn replies that hit the cache [VERIFIED data; cause INFERRED, §7.4].
(d) Each round optimised one number with no counter-metric (Goodhart).

**The one coherent change (detail in §10):** write the spec once (SAFETY rules are enforced, SHAPE rules are
measured). Replace the repair pipeline with a **remove-only, prefix-only** filter that can run sentence by sentence
on a stream. Return a typed `Reply` used by both the app and the bench. Move fact extraction off the critical path.
Make bench runs immutable folders. Gate changes on golden-corpus invariants. On the stored replies, a prototype of
that filter cuts artifacts and lost answers from **81 to 6 of 924**, with zero demoted questions
[VERIFIED: `out/prefix_prototype.md`]. Cost: 12.1% of v2-era replies keep two question marks (Gemma with v1: ≤ 2.3%).

**Decide before starting:** (1) may a reply contain two short questions, or should the stream stop after the
first real question; (2) persona v1 or v3, decided by one measured run, not by more filter work; (3) model:
e4b is the only candidate that fits a 2-second budget; (4) fallback wording; (5) whether "you're not on the
naughty list" may be said (today it is blocked, although the persona asks for reassurance).

---

## 0. Hypotheses scorecard

| # | Verdict | Strongest single piece of evidence |
|---|---|---|
| H1 repair pipeline is order-dependent and only makes odd replies | **PARTLY CONFIRMED** | 45/924 replies (4.9%) change with pass order. All 17 that differ between the round-1 and the current order lose their only question [VERIFIED `out/quality.md`]. Artifacts and lost answers rose every round. But the remedy "regenerate" is **refuted** for this data: P(2nd sample passes \| 1st failed) is 9% for e4b v2 and 19–21% for the others [VERIFIED `out/regen.md`]. The data supports *constrain at the source + remove-only filter*. |
| H2 rules defined in several places that drift | **CONFIRMED** | `safety.check` passes 75.0% of raw replies and `bench.rule_flags` 54.8%; they disagree on 187/924 (20.2%). Words: 45 vs 50. The promise rule exists in 3 versions (`safety.py:11-13`, `bench.py:107`, `run_evals.py:23`) [VERIFIED `out/rule_drift.md`] |
| H3 tests pin behaviour, not properties | **PARTLY CONFIRMED** | Only 4 tests were broken by a later round [VERIFIED `out/test_matrix.md`]. The bigger effect: 0 invariants and 1 corpus test, so every round was green while quality fell. 15 functions assert exact `sanitize` strings, and 6 tests bent the implementation (§6) |
| H4 benchmark not hermetic | **CONFIRMED** | 5 of 7 result files mix two code versions (history_recall + long_session regenerated after 22:41). 447/924 stored answers ≠ current `sanitize(raw)`. judge.json: 0/360 entries hashed, judge model unrecorded, covers 4 of 7 files [VERIFIED `out/bench_audit.md`] |
| H5 failures look like successes | **PARTLY CONFIRMED** | Fixed for the reply path in round 1 (`brain.py:134-147`, `last_error`). Still silent: `extract_facts` swallows every exception (`memory.py:164-165`), judge errors are skipped (`bench.py:486-487`), a warm-up error is overwritten by the next reply (`brain.py:112-113`), logging is `print` [VERIFIED] |
| H6 filter design incompatible with streaming TTS | **CONFIRMED** | `_one_question` keeps the *last* question and D2 keeps the *final* sentence (`safety.py:100-109, 119-126`). Both need the whole reply. `brain.py:126-132` collects the full stream before filtering [VERIFIED]. The prefix prototype shows the alternative works on the same data |
| H7 process causes | **CONFIRMED** | No commits; `evals/bench.py` (817 lines, the most-changed file) is untracked. The review ran during a benchmark run. Rounds 2 and 3 started 4 minutes after the previous report. Round 1 changed +744/−160 lines in about 18 minutes [VERIFIED §1, §9] |
| H8 Santa class mixes concerns | **CONFIRMED** | `Santa.reply` cyclomatic complexity 13 → 19 → 22 across rounds (radon). It does redaction, prompt building, history, warm-up policy, network, timing, filtering, error mapping, logging, extraction and saving (`brain.py:98-159`). Tests need an env-var hack before import (`conftest.py:17-25`) [VERIFIED `out/radon_cc.txt`] |

---

## 1. Churn analysis (H3, H7)

Versions compared: `idx` = git index (staged 21:10), `s0` = `.snapshots/pre-fix-…2326` (identical to `evals/backup/pre-fix-2241`),
`s1` = after round 1, `s2` = after round 2, `cur` = after round 3 [VERIFIED `experiments/churn.py`, `out/churn.md`].
R0 is an undocumented fix session between 21:10 and 22:41 (template bug + single-word emphasis).

| File | R0 | R1 | R2 | R3 | lines first → now |
|---|---|---|---|---|---|
| santa/safety.py | +11/−3 | +131/−22 | +21/−4 | +24/−2 | 63 → 219 |
| santa/brain.py | +22/−4 | +58/−15 | +37/−3 | 0 | 72 → 167 |
| santa/memory.py | +1/−0 | +121/−17 | 0 | 0 | 60 → 165 |
| evals/bench.py | +51/−3 | +352/−90 | +26/−8 | +43/−18 | 464 → 817 |
| **all 9 tracked files** | +107/−12 | **+744/−160** | +101/−17 | +67/−20 | |

The pipeline line itself changed twice (`safety.py:145`): `_truncate(_clean)` → `_one_question(_truncate(_clean))` (R1) →
`_one_question(_truncate(_one_question(_clean)))` (R2) [VERIFIED].

**Hotspots** (16 units touched in ≥ 2 rounds, 6 in ≥ 3; full list in `out/churn.md`). What each round changed and what broke next:

| Unit | Rounds | Change → what broke next |
|---|---|---|
| `_clean()` | R0, R1 | R0 kept single-word `*x*` but still deleted bold and multi-word spans (S1) → R1 "never delete arbitrary text between asterisks" → **stage directions became speech**: replies with a spoken stage direction went 6 → 44 of 924 ("gently pats shoulder", "adjusts glasses", "nibbles") [VERIFIED `out/quality.md`]. Flagged in FIXES3, not fixed |
| `_truncate()` | R1, R3 | R1 abbreviations and teaser drop, but the cap counted "Ho ho ho!" as a sentence → with R1's one-question rule, a lone echo question was the only question in 67 replies (FIXES2) → R2 moved the rule → R3 D1 (opener free) + D2 (keep final question, drop middle) → **answer lost 2 → 29, dangling "Or…" 0 → 12, echo + question 0 → 34** |
| one-question rule (`_one_question` + `sanitize_ex` composition) | R1, R2 | R1 keep last, after the cap → echo-only questions → R2 before **and** after the cap → replies that lost all their questions 22.5% → 38.7% of 924 (FIXES2's 49.9% also counts the 11.1% of raw replies that never had a question); demoted questions 64 → 200; 17 replies lose their only question because of the order |
| `BLOCKLIST` | R1, R2, R3 | R1 gift promise and brand names → "You'll get a big hug" and "Gemma" blocked → R2 gift-word window and brand *claims* only → "I will bring you" vs "I'll bring you" inconsistent → R3 removed the bare entry |
| `build_system_prompt()` / `kids_block()` | R1 | Active child's facts only (I1) → the unsafe `ALL` default kept for old tests (`persona.py:63`); the prompt now differs per speaker (latency, §7.4, INFERRED) |
| `Santa.reply()` | R0, R1, R2 | history window → error fields/timeouts/extraction gating → warm-up and idle re-warm inside `reply()` |
| `manifest()`, `export_blind()`, `V2_MODELS` | R0–R3 | R1 manifest test pinned label "v2" → broken by R2 (v3 persona) → fixed in R3; `V2_MODELS` → `LEGACY_V2_MODELS` |

**Tests per round** [VERIFIED `out/churn.md`, `out/test_matrix.md`]:

| | s0 (review) | s1 | s2 | cur |
|---|---|---|---|---|
| test functions | 70 (46 xfail) | 138 (+68) | 172 (+34) | 204 (+32) |
| results, with its own code | 25 pass / 73 xfail | 196 / 1 xfail | 254 / 1 fail / 1 xfail | 294 / 3 fail / 1 xfail |
| existing test bodies edited | — | 0 (45 xfail markers removed) | 0 | 1 (the H1 manifest fix) |

Tests broken by a later round: 4 in total. `test_manifest_command_matches_result_files` (R1 test, broken by R2), and three
round-2 tests broken by R3 (`test_a_echo_question_is_not_left_as_the_only_question`, `test_a_only_cap_removes_sentences`,
`test_a_reply_may_end_with_no_question`). One review test has failed since round 1 by contradiction (E4 vs S4).
15 test functions assert an exact `sanitize`/`_truncate` output string; 3 assert exact report text or row format [VERIFIED `out/test_classify.md`].

---

## 2. Rule inventory and drift (H2)

| Rule | persona.py | config | `sanitize` | `check` | bench | run_evals | Agree? |
|---|---|---|---|---|---|---|---|
| Sentences | "1 to 3 SHORT sentences" (l.8) | `MAX_SENTENCES=3` (l.27) | opener + 3; D2 can give opener + 2 (`safety.py:96-112`) | — | > 3 on raw, any "ho ho" sentence free, no abbreviations (`bench.py:123-126`) | — | **No**: 3 counting methods; disagree on 25/924 cap decisions, exact counts differ on 70/924 |
| Words | "SHORT" | `MAX_WORDS=45` | cut at 45 + "!" (`safety.py:113-115`) | > 50 (`l.134`) | > 50 (`bench.py:125`) | `check` on filtered | **No** (45 vs 50) |
| Questions | at most one; "often fine to ask nothing" (l.16-18) | — | keep last, demote others; D2 forces a final question (`safety.py:100-126`) | > 1 | > 1 on raw | `check` on filtered (cannot fire any more) | **No**: the round-3 test requires ≤ 30% no-question replies (`test_fixes_round3.py:117`), against the persona's "often fine to ask nothing" |
| Stage directions | none; "never write actions like *waves* or giggles" (l.19, 46) | — | deletes only spans made of 40 listed words (`safety.py:36-44`) | — | any `*…*`/`(…)`/`[…]` (`bench.py:103`), including emphasis | — | **No**: bench flags 146 emphasis-only replies (e.g. `*big*`); runtime speaks 43 real stage directions |
| Markdown / emoji | none (l.19) | — | strip (`safety.py:71,75`) | — | narrower emoji class (`bench.py:105-106`) | — | close (0/924 emoji) |
| Gift promise | never promise a specific gift (l.32) | — | promise + gift noun within 6 words; "I promise" always (`safety.py:6-13`) | via blocklist | any "you'll get"…, **no curly ’** (`bench.py:107`) | third list (`run_evals.py:23`) | **No**. 19/924 raw replies use ’ forms that the bench cannot match. "maybe they'll have one ready for you under the tree" passes all three (`labels60.md` #52) |
| AI / brand | never discuss being an AI (l.40-41) | — | claims only (`safety.py:14-19,31`) | via blocklist | any *mention* of gemma/google/mistral… (`bench.py:108-110`) | — | **No** (deliberately different, but not named as different) |
| Naughty list | say every child is on the nice list (l.43) | — | blocks any "naughty list" (`safety.py:25`) | via blocklist | via blocklist | — | **Conflict**: "You are NOT on the naughty list" → fallback (`out/probes.md`). Latent: 0/924 replies said it |
| Prices / stores | never mention (l.33) | — | `dollars`, `amazon` only | — | — | — | gaps (INFERRED: "$500", other store names) |
| Private data | do not repeat (l.44) | — | one `private_kind` for input, facts and output (`safety.py:192-219`) | — | none | — | single source (good) |
| Fallback line | — | — | `FALLBACK` (`safety.py:46`) | — | `OLD_FALLBACK` too (`bench.py:429`) | compares to `FALLBACK` | ok |

**Measured on the 924 raw replies** [VERIFIED `out/rule_drift.md`]: valid under `check` 693 (75.0%); under `rule_flags` 506 (54.8%);
unchanged by `sanitize` 505 (54.7%). `check` vs `rule_flags` disagree on 187 (20.2%), all in one direction (`check` is laxer).
Five examples are in `out/rule_drift.md`; typical: a Ministral reply with `*sniffles*` and 4 sentences passes `check`.

**Which should win:** a single `santa/spec.py` used by the app and the bench. Use the runtime's patterns for safety (the most refined:
gift window, curly apostrophes, brand claims). Count sentences the runtime way (after cleaning, abbreviation-aware, leading opener free).
The bench's "mentions a brand" stays as a separately named *measurement*, not a second copy of the safety rule. `check()` and
`run_evals.py` should be deleted (nothing at runtime calls `check`; grep shows only `run_evals.py:35`, on filtered text).

---

## 3. Spec-level experiments on the filter (H1, H3)

Script `experiments/filter_properties.py`: the 924 raw replies, 20,000 structured Santa-like replies and 20,000 random-noise strings.
Hypothesis supplied the shrunk minimal examples [VERIFIED `out/filter_properties.md`].

| Property | 924 real | 20k structured | 20k noise |
|---|---|---|---|
| P1 idempotent | 0 fail | 0 | 2,789 (e.g. `'[()]'` → `'()'` → FALLBACK) |
| P2 ≤ 1 "?" and ≤ 45 words | 0 | 0 | 4,596 (`'??'` survives: the rule only demotes *earlier sentences*) |
| P3 negation survives in kept sentences | 0 | 0 | 104 (`#` stripping joins words: `a#no` → `ano`) |
| P4 no invented or reordered words | 0 | 0 | 6,258 (same joining) |
| P5 final question kept when the reply fits | 0 | 310 (teaser drop: `'Ho ho ho! You know what?'` → `'Ho ho ho!'`) | 0 |
| P6 no private data in output | 0 | 0 | 0 |

Realistic probes (`out/probes.md`): a question inside quotes or after an em dash escapes the one-question rule
(`A dinosaur?—a pony? What fun!` keeps 2 "?"). Negation inside markup now survives (`*not at all*` → `not at all`), which is the S1 fix working.

**Order independence (P7):** of the 6 alternative orders of clean / one-question / truncate, at least one changes the output
for **45/924 (4.9%)**. The round-1 order (C, T, Q) differs from today's on 17; in **all 17** today's order leaves no question,
because the real question is demoted before the cap removes the later one [VERIFIED `out/quality.md`].

**Monotonic quality** (`experiments/quality.py`; heuristic tags defined in its docstring). The same 924 raw replies through each version:

| Version | material change | dropped sentences | question demoted | question lost (raw had one) | stage direction spoken | ".!" debris | dangling "Or…" | answer lost | echo + q | **artifact or answer lost** |
|---|---|---|---|---|---|---|---|---|---|---|
| idx (21:10) | 50.1% | 49.9% | 0 | 21.5% | 0 | 0 | 9 | 7 | 0 | 16 (1.7%) |
| s0 | 46.3% | 46.1% | 0 | 22.3% | 6 | 0 | 3 | 6 | 0 | 15 (1.6%) |
| s1 (R1) | 48.6% | 43.5% | 6.9% | 22.5% | 44 | 3 | 0 | 2 | 2 | 45 (4.9%) |
| s2 (R2) | 48.6% | 43.5% | 21.6% | 38.7% | 44 | 6 | 0 | 2 | 0 | 48 (5.2%) |
| cur (R3) | 32.8% | 24.8% | 17.6% | 3.6% | 43 | 6 | 12 | 29 | 34 | **81 (8.8%)** |

Current filter, by file: artifact or answer lost = gemma4-12B v1 0, e4b v1 0, e4b v2 5, gemma4-12B v2 0, ministral14B 24,
ministral8B-Q4 28, ministral8B-instr 24. By persona: v1 0/264, v2 81/660. "Material change" counts content dropped, meaning
changed or fallback, but not pure markup removal.

**Reading:** the hard guarantees hold on real data. Breakage shows up only in *quality*. Every repair rule converts one
failure into another, and no round measured the conversion.

---

## 4. Response audit (how the replies read to a child)

**(a) Intervention rate** (current filter, material change, per file; denominator 132 each) [VERIFIED `out/quality.md`]:
gemma4-12B v1 **2.3%**, e4b v1 **0.0%**, e4b v2 25.8%, gemma4-12B v2 16.7%, ministral14B 63.6%, ministral8B-Q4 59.1%, ministral8B-instr 62.1%.

**(b) 60-pair stratified sample**, labelled by hand (`out/sample60.md`, labels with reasons in `out/labels60.md`).
The labeller was not blind and no TTS was used. Of the 45 pairs the filter materially changed:
**better 4 (8.9%), same 12 (26.7%), worse 29 (64.4%)**. The other 15 pairs (e4b v1 and gemma v1 slots) were unchanged.

| Worse, by type (29) | n | example |
|---|---|---|
| lost answer | 7 | goldfish → "Oh, Ziv... Do you have another pet you love?"; reindeer names → "Ho ho, Ziv! Or a reindeer too?" |
| dangling fragment | 6 | "Big red truck, oh my! Red too?" |
| demoted question | 5 | "Who am I talking to." |
| lost warmth | 4 | the "I'll tell my elves" deflection dropped |
| meaning changed | 3 | bossy case: "A better wish than Leo's, Ziv." now sounds like Santa agrees |
| echo-only | 3 | "Pickles. Do cats like cookies?" |
| artifact | 1 | "Pickles.! What color is he?" |

**(c) Fixability of the 29 worse cases** (primary route): regeneration/source 28, smarter filter 1. Secondary routes: prompt 14,
smarter filter 8, model choice 6. Decoding settings: 0. A stop sequence cannot pick *which* sentences to keep.
A smarter filter only moves the failure: guarding "Or…" tails sends the reply back to no question, and so on.
The more useful finding is where the failures come from: **all 29 are replies that broke the persona's shape rules in raw.**
Under persona v1, e4b needed 0 material repairs and gemma4-12B 3 (all demoted "Who am I talking to?").

**What the data cannot tell us** (UNKNOWN): how TTS renders a demoted question or ".!"; how a 3-year-old reacts; anything
about persona v3 (no data); whether my labels match yours (one labeller, not blind).

---

## 5. Repair vs regenerate vs constrain (H1, H6)

All from stored data [VERIFIED `out/regen.md`; latency caveats in §7.4]. "Pass" = acceptable after a remove-only clean
(no blocklist or private hit, ≤ 1 "?", ≤ opener + 3 sentences, ≤ 45 words, no spoken stage direction, not cut off by max_tokens).

| Model / persona | pass, remove-only | 2nd sample passes after a fail (single-turn, ordered pairs) | design B K=2: p50 / p95 / ends in fallback | est. first sentence p50 / p95 | full reply p50 / p95 |
|---|---|---|---|---|---|
| e4b v1 | **100%** | n/a (no fails) | 1.07 / 3.98 / 0% | 0.68 / 3.70 | 1.07 / 3.98 |
| e4b v2 | 73% | **9%** (22 pairs) | 1.65 / 9.62 / 21% | 0.56 / 4.22 | 1.33 / 4.81 |
| gemma4-12B v1 | 98% | 0% (6 pairs) | 3.35 / 12.9 / 2% | 2.02 / 11.6 | 3.36 / 12.8 |
| gemma4-12B v2 | 83% | 21% (28) | 4.95 / 16.5 / 12% | 2.20 / 12.7 | 4.63 / 15.1 |
| ministral (3 files) | 29–34% | 19–21% (96 each) | 6.2–14.6 / 16–27 / 55–59% | 0.97–1.79 | 3.3–7.9 |

How weak the "2nd sample" estimate is: 20 single-turn cases × 3 samples, and samples within a case are correlated. Treat it as ±15 points.
It still says something clear: **failures stick to the prompt, not to chance**. Resampling the same prompt rarely helps.
Stop conditions: "stop at the first '?'" lands on an echo question in 19–26 replies per file for e4b v2 and Ministral.
"Stop after opener + 3 sentences" is acceptable for 86–100% of Gemma replies; Ministral saves ~1 s of generation with it.

| Design | Latency | Complexity | Safety | Streaming |
|---|---|---|---|---|
| A current repair pipeline | 1 reply | high (order-dependent, 15 exact-string tests) | blocklist/private checked only on the kept text | **no** (keeps the last question, drops the middle) |
| B validate + regenerate (K=2) | e4b v2 p95 4.8 → 9.6 s; 21% still fail | medium | same as A | no (validates whole replies) unless validation is per sentence |
| C source constraint + remove-only prefix filter | 1 reply; first audio after the first sentence (~0.6 s e4b) | low | per sentence; a hit stops the stream (fallback if nothing was spoken) | **yes** |

**Recommendation for show day: C.** On the stored replies the prototype gives 6/924 artifact-or-lost (vs 81) and 0 demoted questions.
It costs 12.1% two-question replies on v2-era data [VERIFIED `out/prefix_prototype.md`]. Variant B (stop after the first real
question) cuts two-question replies to 4.9% but loses answers in 21 replies [VERIFIED `out/prefix_variant_b.md`].
**With no deadline:** the same C, plus a small corrective-retry experiment: when the *first sentence* breaks a SAFETY rule, regenerate once
with an explicit instruction. Also try a fine-tuned or few-shot persona for shape. Neither is worth building before Phase 2.

---

## 6. Test-suite audit (H3)

Classification (AST heuristics, `out/test_classify.md`; 204 functions, 298 cases): harness 54, exact-string snapshot 28, mock-heavy 40,
example-based 81, **property/corpus 1**.

**Contradictions and tests that shaped the implementation** [VERIFIED]:
1. `test_bench::test_jailbreak_case_has_persona_check` expects `"Okay! I am ChatGPT!"` to survive `sanitize`, while `test_safety::test_ai_identity_blocked` requires it to be blocked. One must fail.
2. `test_brain::test_redaction_text_reaches_history_and_transcript` (`test_brain.py:116`) **pins the P3 bug** ("where they live" for a phone number). The fix had to write a contorted phone message to keep it green (`safety.py:182-183`).
3. `test_parse_speaker_case_insensitive_known_name` and the Zoë/Mary-Kate tests vs the "registered child only" rule. Result: a new "guest speaker" concept (`brain.py:63-76`).
4. `test_persona.py:10` calls `build_system_prompt(prof)` and expects all facts. Result: the unsafe `ALL` default was kept (`persona.py:63`).
5. `test_memory::test_save_interrupted_keeps_old_file` mocks `Path.write_text`, so `save` must use `write_text` (FIXES dispute 5).
6. `test_bad_cases_reflect_what_child_hears` needs the row to end in `| 0 |`, so the report labels were bent (FIXES dispute 9).
7. Three round-2 exact-output tests vs round-3 D1/D2, and the round-1 manifest test vs round-2 v3 (§1).
8. `test_d_stored_replies_rate_and_word_cap` (≤ 30% no-question) contradicts the persona's "often it's fine to ask nothing".

**Proposed spec layer** (`tests/spec/`, about 14 checks; corpus = a frozen JSONL copy of the 924 raw replies plus child text).
Each check is listed with the round regression it would have caught:

| # | Check | Threshold | Would have caught |
|---|---|---|---|
| S1 | heard is a sentence-boundary **prefix** of the cleaned raw (modulo removed spans), or FALLBACK | 0 failures | R1 demotion, R2 order loss, R3 middle-drop/dangling |
| S2 | never adds or rewrites punctuation: no new ".!", "?" count never rises, no "?"→"." | 0 | R1/R2 demotion, ".!" |
| S3 | no invented words (in-order subsequence) | 0 | — (guard) |
| S4 | idempotent | 0 | — (guard) |
| S5 | ≤ 45 words, ≤ opener + 3 sentences | 0 | — |
| S6 | negations in kept sentences survive | 0 | S1 (review) |
| S7 | no blocklist/private match in heard; a sentence with a hit is never spoken | 0 | P1 (review) |
| S8 | no spoken stand-alone stage direction | 0 | R1 stage leftovers (6 → 44) |
| S9 | answer-lost heuristic | ≤ 1% (prototype 0.5%) | R3 (2 → 29) |
| S10 | fallback rate | ≤ 0.5% | blocklist over-reach |
| S11 | streaming equivalence: random chunkings give the same heard text | 0 over 924 × 5 | Phase 2 regressions |
| S12 | bench and app import the same rule functions (no rule regex in `bench.py`) | structural | H2 drift |
| S13 | every fallback path sets `Reply.reason` | 0 | H5 |
| S14 | `reply()` makes exactly one model call (no extraction) | structural | latency |
| report | two-question rate, no-question rate, words heard, per model | printed, not gated | Goodhart guard |

**Keep:** the blocklist/no-false-positive/private/counting/emoji/negation examples from `test_safety.py` (as a spec table);
memory (atomic save, tolerant load, JSON parsing); brain (timeout, role alternation, error visible, extractor sees only the child's words);
persona (active-only facts, newline); the warm-up tests; and the bench tests for error exclusion, judge hash and leak on every turn
(rewritten for the run-folder format). **Merge** the ~12 one-question/cap tests into S1/S2. **Retire:** the 15 exact-string
sanitize tests, the 30% test, `check()` tests, the E4 contradiction, the "where they live" pin (fix the message instead),
report-row-format tests, and the "one key per item in judge.json" constraint.

---

## 7. Benchmark design audit (H4, H5)

Ways a number in `bench_report.md` can be wrong or non-comparable today [VERIFIED `out/bench_audit.md` unless noted]:

| # | Problem | Code today | Data today |
|---|---|---|---|
| 1 | `bench_report.md` was produced by the **pre-round-1** bench (23:21:28): no "n", no Errors row, still claims a "different model family" judge | — | **remains** until re-run |
| 2 | BENCH_ONLY merge: 5/7 files hold history_recall + long_session from post-22:41 code, everything else from earlier code | records `previous` meta, still merges into one file (`bench.py:350-357`) | **remains** |
| 3 | stored `answer` is from the s0 filter; 447/924 differ from today's `sanitize(raw)`; `resanitize`/`recheck` rewrite files in place (`bench.py:674-704`) | in-place mutation remains | **remains** |
| 4 | judge cache keyed by id | **fixed** (hash, `bench.py:448,470`) | 0/360 hashed → every judge number in the report is stale; 125 judged answers differ from today's filter output |
| 5 | judge is a contestant (ministral3:14B), model unrecorded | judge model is a parameter and recorded | no non-contestant judge identified (UNKNOWN which one) |
| 6 | persona label from env var / hard-coded list | `persona_sha` recorded for new runs | old files rely on `LEGACY_V2_MODELS` (`bench.py:709`); **no file measures v3, the persona the app runs** |
| 7 | raw vs filtered mixing | two "fail every sample" rows added | words, content checks and judge use the stored (old-filter) answer; "clean %" uses raw flags; filter changes alone flip recall (100 → 95.2% for two Ministral models) and leak checks |
| 8 | errors counted as replies | **fixed** for new runs (`is_failed`) | old files inferred from an empty raw reply |
| 9 | silent errors | judge exceptions skipped (`bench.py:486`); extraction exceptions return `[]` (`memory.py:164`) | remains |
| 10 | sample size | n printed (fixed) | N=3, 20 single cases; persona n=3–15 |
| 11 | **latency pooled and unrepresentative** | single-turn (TTFT p50 0.04 s for e4b: cache hits) pooled with multi-turn (1.06–1.24 s); fact-extraction time not timed | remains (new finding, §7.4) |
| 12 | global monkeypatching (`memory.save` at import, `memory.extract_facts` swapped, `bench.py:35,301,320`) | harness hazard for any importer | remains |
| 13 | `run_evals.py` is a second harness the README still recommends | `check()` on filtered text | remains |

**7.4 Latency, measured differently** [VERIFIED `out/bench_audit.md`, `out/extraction_latency.txt`]:
- e4b full reply p50: single-turn 0.90 s, multi-turn 1.72 s (v1) / 2.52 s (v2). With memory extraction on (long_session):
  **3.37 s (v1) / 4.33 s (v2), TTFT 2.7 / 3.6 s**. Fact extraction adds 0.74–0.85 s *inside* `reply()` before it returns.
  gemma4-12B with memory: **11.6 / 12.9 s** full reply. Ministral 8B: 7.5–8.8 s.
- TTFT by turn (e4b v1, history_recall, extraction off): 0.29, 2.91, 2.79, 0.23, 0.31, 0.30, 1.71 s. The slow turns are exactly
  where the prompt prefix changes: a new child name is added to `kids_block` (turns 1 and 2), and the 12-message window starts
  sliding (turn 6). With memory on, facts change the system prompt every turn and the prompt differs per speaker (`persona.py:81`).
  **Cause INFERRED** (llama.cpp prefix cache invalidated); the pattern is VERIFIED.
- So at the show, e4b currently needs about **4 s** from the child finishing to Santa's text existing (non-streamed), not 1.1–1.3 s.
  That is over your "couple of seconds". INFERRED from the long_session numbers; UNKNOWN with STT/TTS also running.

**Smallest hermetic design:**
```
evals/runs/<YYYYmmdd-HHMM>-<model-slug>-<persona-label>/     (written to a .tmp dir, then renamed; never edited)
  manifest.json   persona_sha, spec_sha, sha of every santa/*.py + bench.py + cases.json, git commit (if any),
                  model id + `docker model inspect` digest, temperature, max_tokens, extra_body, N, only=[...],
                  started/finished, python + openai versions
  turns.jsonl     one Reply per line: raw, heard, spoken sentences, reasons, shape flags, error,
                  ttft, first_sentence_s, total, extract_s, ctx, case/scenario/sample/idx
  judge-<judge-slug>.json   {id: {scores, answer_sha, rubric_sha}}
```
`bench.py report RUN…`: one column per run. Every cell is `x/n (pct)`. Separate latency rows for single-turn and multi-turn-with-memory.
"Heard" is either the stored text or recomputed with the *current* spec, and the header says which. The report refuses to put two personas
in one table without `--allow-mixed`. A partial (`only`) run is its own folder and is never merged.

---

## 8. Architecture audit (H5, H6, H8)

There is no pipeline object. `Santa.reply()` (`brain.py:98-159`, complexity 22) returns a `str` and leaves results in side-channel attributes
(`last_raw`, `last_stats`, `last_error`). The bench reads those attributes (`bench.py:274-276`). Policy lives in five places (§2).
Streaming: tokens are collected fully, then `sanitize_ex` runs, and its keep-last-question and keep-final-sentence rules need the whole text.
Hard to test: the network call and the clock inside `reply()` (the `_now` hook was bolted on in R2), disk I/O in `__init__`
(`memory.load`) and in `reply` (`memory.save`), and module-global monkeypatching in the bench.

**Target structure: the smallest change, not a rewrite.**
```python
# santa/spec.py  -- pure, no I/O; the ONLY place reply rules live
MAX_CONTENT_SENTENCES = 3; MAX_WORDS = 45
def clean(text: str) -> str                          # remove-only: markdown, emoji, action-only and stand-alone stage spans
def split_sentences(text: str) -> list[str]          # today's _SENT_SPLIT
def safety_reason(text: str) -> str | None           # "blocklist" | "gift_promise" | "ai_identity" | "private" | None
def shape_flags(raw: str) -> list[str]               # measurement only: "questions>1", "sentences>3", "words>45", "stage", "markup"

# santa/speech.py -- streaming-compatible
def sentences_from_stream(chunks: Iterable[str]) -> Iterator[str]
def speak(sentences: Iterable[str]) -> Iterator[str]  # prefix-only; stops on a safety hit or a cap; never rewrites
@dataclass
class Reply:
    text: str; raw: str; spoken: list[str]; reason: str | None; error: str | None
    shape: list[str]; ttft: float; first_sentence_s: float; total: float

# santa/brain.py
class Santa:
    def __init__(self, model=..., base_url=..., client=None, profiles=None)   # injectable: no conftest env hacks
    def build_messages(self, speaker, text) -> list[dict]                     # pure given state
    def reply(self, speaker, text) -> Reply                                   # one model call; no extraction, no save
    def reply_stream(self, speaker, text) -> Iterator[str]                    # Phase 2: yields spoken sentences
    def remember(self, speaker, child_text) -> list[str]                      # extraction + save, called after speaking
```
`safety.sanitize(text)` stays as a thin wrapper (`"".join(speak(split(clean(text))))`) for old callers. The bench calls
`spec.shape_flags` / `spec.safety_reason` and stores `Reply` fields.

---

## 9. Process audit (H7)

Reconstructed from file mtimes, the git index and the documents [VERIFIED `stat` listing; quotes from FIXES*.md]:

| Time (Nov 4–5) | Event |
|---|---|
| 19:46–20:02 | project created; `run_evals.py` reports |
| 21:10 | `git add` (the index is the only git record); backup `20261104-2110` (which later received 22:40 result files) |
| 21:51 | `judge.json` written (4 of the later 7 files) |
| ~22:41 | undocumented fix session (R0: template bug, single-word emphasis); backups `pre-fix-2241` |
| 22:41–23:21 | BENCH_ONLY re-run of 2 scenarios **while the review was being written** (REVIEW.md:14) |
| 23:21:27 | all 7 result files rewritten (merge + resanitize + recheck), report written 1 s later by pre-R1 code |
| 23:26 → 23:44 | snapshot, then **round 1: +744/−160 lines and 99 tests in ~18 min** |
| 06:17 → 06:24 | round 2 (7 min) |
| 06:28 → 06:34 | round 3, **started 4 min after FIXES2.md** |
| 06:35:51 | Python **3.10** bytecode written into `santa/__pycache__` by some other process (the documented runs used 3.14 with PYTHONDONTWRITEBYTECODE) |

Where instructions caused problems [VERIFIED from FIXES*.md]: "fixed only when the review's own test passes" made example tests the goal.
"Only FIX A, B, C" left the known "Ho ho ho counts as a sentence" cap issue for another round (FIXES2 §4). "Do not edit existing tests"
left stale tests failing and invented workarounds (guest speakers, the phone message). A one-number threshold ("no-question rate above 30%
→ implement D2") produced the middle-dropping. Where missing commits cost you: no bisect; the code behind each result file had to be
reconstructed (MANIFEST, `LEGACY_V2_MODELS`); `bench.py` is untracked; `profiles.json` is staged (privacy risk, still open).

**Five working rules for the remaining 19 days**
1. **Commit before and after every change** (add `bench.py`, ignore `profiles.json`). Snapshots and backups stop. A commit message names the corpus numbers it moved.
2. **Nothing runs while code changes.** Bench runs only on a committed tree, write an immutable run folder, and are never merged or re-sanitized in place.
3. **Spec first.** A behaviour change starts as an edit to `spec.py` plus the corpus metric it should move *and* the counter-metric that must not move. Acceptance = golden-corpus checks, not new example tests.
4. **A person reads 20 changed pairs before accepting** any change to what children hear (`experiments/quality.py` writes them). No back-to-back fix rounds.
5. **One editing session at a time, allowed to update superseded tests in the same change** (with the reason in the commit). Reviewers hand over failing spec checks, not fix lists.

---

## 10. The one coherent change

Ordered. Effort is focused hours. Every acceptance threshold is measured on the frozen 924-reply corpus unless stated otherwise.

| # | Item | Removes (evidence) | Files / functions | Acceptance | Risk | h |
|---|---|---|---|---|---|---|
| 0 | Freeze: commit the current tree; add `evals/bench.py`; ignore `profiles.json`; copy the 924 raw replies + child text to `tests/spec/golden.jsonl` | H7; no baseline | git, `.gitignore`, new `tests/spec/golden.jsonl` | the commit exists; golden file has 924 lines, sha recorded | none | 0.5 |
| 1 | `santa/spec.py`: one table of rules marked SAFETY (enforced) or SHAPE (measured) | H2 (20.2% disagreement, 3 promise lists) | new `spec.py`; `safety.py` patterns move there; `check()` deleted | S12: no rule regex left in `bench.py`/`run_evals.py`; persona numbers asserted equal to spec constants | low | 1.5 |
| 2 | Remove-only prefix filter replaces `_one_question`, D2 and the double pass | H1/H6 (81 → 6 artifacts or lost answers in the prototype; goldfish case) | new `speech.py` (`sentences_from_stream`, `speak`); `safety.sanitize_ex` becomes a wrapper; `_truncate`'s D2 branch and `_one_question` deleted | S1–S11 all at 0 failures; answer-lost ≤ 1%; fallback ≤ 0.5%; two-question rate reported (prototype 12.1% on v2 data) | medium: two-question replies are spoken | 4 |
| 3 | Typed `Reply` returned by `Santa.reply`; the bench consumes it | H5/H8 side-channels | `brain.py` (`Reply`, `build_messages`, optional `client`/`profiles` args); `bench.py` `_turn_result`, `rule_flags` → `spec.shape_flags`; delete `run_evals.py`; fix README | S13; bench tests pass against `Reply` | low | 3 |
| 4 | Fact extraction off the critical path | +0.7–2.8 s inside `reply()` | `brain.reply` (remove the extraction block), new `Santa.remember`; `chat.py` calls it after printing | S14: `reply()` makes 1 model call; existing redaction/registered-only tests move to `remember` | low | 1.5 |
| 5 | Prefix-cache-friendly prompt: constant system prompt per session (all names/ages); active child's facts in a note on the *current* request only (not stored in history); trim history in blocks, not one message at a time | §7.4 (TTFT 2.7 s with memory, slow turns = prefix changes) | `persona.build_system_prompt`, `brain.build_messages` | unit: system prompt identical across speakers and turns; live: e4b multi-turn-with-memory TTFT p50 ≤ 0.6 s (now 2.7 s); cross-child leak rate not worse | **medium**: cause INFERRED; template handling of a trailing note UNKNOWN; facts in the user turn may change behaviour | 3 + 1 live |
| 6 | Immutable bench run folders + manifest; report with denominators; separate latency rows; no merge | H4 (5/7 mixed files, 48.4% stale answers, 0/360 hashed judge) | `bench.py` `gen`, `report`, `judge`; delete `resanitize`/`recheck`/`manifest`/`LEGACY_V2_MODELS` | every cell `x/n`; report refuses mixed personas; a re-run writes a new folder (test in a temp dir) | low | 4 |
| 7 | Spec test layer; retire/merge per §6 | H3 | `tests/spec/test_spec.py`; prune `tests/review` | S1–S14 green; no exact-string sanitize assertions left | low | 2.5 |
| 8 | Measure, then choose: e4b × persona v1 vs v3, one run each through the new bench; read 20 replies each | persona responsibility (v1 0% vs v2 25.8% interventions; v3 unmeasured) | none (model time ~30 min) | the owner picks on raw shape-compliance, TTFT/first-sentence latency and the reading | none | 1 |

Total ≈ 22 h + ~1.5 h of model time. Phase 2 starts Nov 12, so items 0–7 fit in Nov 5–8 with time to spare.

**Do NOT build:** regeneration or best-of-N loops; an LLM judge or second model as a runtime gate; any smarter rewriter
(question demotion, choosing middle sentences, connective guards); grammar- or JSON-constrained decoding; NLP libraries for
sentence splitting; a results database; CI; dashboards; async frameworks; more blocklist cleverness than the spec table; persona
edits made inside the filter work.

**Rollback without git:** before item 2, copy `santa/` to `santa/legacy/`. Add `SANTA_FILTER=legacy|prefix` to `config.py`
(default `prefix`); `legacy` routes `Santa.reply` through `santa.legacy.safety.sanitize_ex`. Rolling back = setting one environment
variable. Old bench files stay untouched in `evals/results/`; new runs go to `evals/runs/`, so nothing is overwritten.
Delete `santa/legacy/` after the show.

**Minimum viable version (one day, ~8 h):** items 0, 2 (with the `sanitize_ex` wrapper so nothing else changes), 4, the S1/S2/S5/S7/S8/S11
subset of 7, and item 8 run through today's bench with `BENCH_TAG` set (accept today's report flaws for one comparison).

**What you must decide before it starts:**
1. Two short questions in one reply: allowed (prototype A: 12.1% on v2-era data, ≤ 2.3% for Gemma v1), or stop after the first real question (variant B: 4.9%, but 21 lost answers)?
2. May Santa ask no question? The persona already says yes. If yes, delete the 30% target.
3. Persona v1 vs v3, by item 8 (not by more filter work).
4. Model: e4b (the only one near the latency budget; 12B is 2–3.5× slower in multi-turn, 11.6 s vs 3.4 s full reply with memory on). Drop Ministral (8–10% clean raw; 212/396 = 54% of its replies contain a stage direction, Gemma 0/528, `out/stage_share.md`).
5. Fallback line wording, and whether a SAFETY hit on the *first* sentence should regenerate once (data: 1/924 fallbacks, so I recommend no).
6. "You are not on the naughty list": allow it, or keep it blocked (0/924 occurrences)?
7. Target latency for Phase 2 (suggested: first audio ≤ 1.5 s p95 in a multi-turn session with memory on).

**What the data implies about persona vs filter responsibility** (no persona text proposed): shape (length, number of questions, echo style)
is decided by the persona and the model. e4b v1 needed 0/132 repairs; v2 needed 34/132, driven by the echo bullet whose example ends in "?".
The filter should own only safety and markup. Ministral's stage directions survive the persona's explicit ban, so that is a model choice, not a prompt fix.

---

## 11. Confidence, sensitivity, files

**Confidence in the recommended change: medium-high.** The filter evidence is direct, reproducible and on your own 924 replies
(version-by-version table, prototype comparison, hand-labelled sample). The latency part (item 5) is the weakest: the turn pattern is
verified, the cause is inferred. Persona v3's behaviour is unknown.

**Three facts that would most change the recommendation:**
1. Persona v3 or v1 with e4b in a fresh run shows **> 20% raw shape violations**. Then the filter matters more again; consider variant B or a corrective retry.
2. A **corrective retry** (a different instruction, not a resample) passes > 70% at < 0.7 s extra. Then validate-and-retry on the first sentence becomes worth it.
3. The slow TTFT turns are **not** prefix-cache misses (for example memory pressure in Docker Model Runner). Then item 5 is wasted, and only item 4 helps latency.

**Files created** (all under `tests/audit/`; nothing else in the repo was changed):
- `AUDIT.md` (this report)
- `experiments/_common.py`, `churn.py`, `run_test_matrix.py`, `rule_drift.py`, `filter_properties.py`, `probes.py`, `quality.py`, `regen.py`,
  `test_classify.py`, `bench_audit.py`, `prefix_filter_prototype.py`, `prefix_variant_b.py`, `stage_share.py`
- `experiments/out/`: `churn.md`, `test_matrix.md`, `test_matrix.json`, `rule_drift.md`, `filter_properties.md`, `probes.md`, `quality.md`,
  `sample60.md`, `sample60.json`, `labels60.md`, `regen.md`, `test_classify.md`, `bench_audit.md`, `extraction_latency.txt`, `stage_share.md`,
  `prefix_prototype.md`, `prefix_variant_b.md`, `radon_cc.txt`

**How to re-run** (temp venv outside the repo with pytest, hypothesis, radon, openai 3.45.0):
`cd tools/audit/experiments && PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python <script>.py`. `run_test_matrix.py` copies the trees
into a temp dir and runs pytest there with `-p no:cacheprovider --runxfail`. Nothing calls a model or Docker.

**Side effects noted:** the hypothesis cache that `filter_properties.py` first wrote inside `tools/audit/experiments/.hypothesis` was deleted; the script now uses a temp dir.
One loose git object (`.git/objects/b4/4209…`, the staged `evals/cases.json`) shows mtime 06:40:43. That is before my first git
command; its content and `.git/index` are unchanged. `santa/__pycache__/*.cpython-310.pyc` (06:35:51) predates this audit.
