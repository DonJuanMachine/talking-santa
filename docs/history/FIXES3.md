# Round 3 fixes

Applied 2026-11-05 on top of rounds 1 and 2 (`FIXES.md`, `FIXES2.md`, not edited). Only FIX D, E, F, H and the evidence step were done.
A row is **fixed** only when its test passes.

## 1. Fix → status → test (new tests are in `tests/review/test_fixes_round3.py` unless noted)

| Item | Status | Test(s) |
|---|---|---|
| D1 leading interjection opener does not count toward the 3-sentence cap | fixed | `test_d1_opener_plus_three_sentences_kept`, `test_d1_reply_without_opener_keeps_the_three_sentence_cap`, `test_d1_all_interjection_openers_behave_the_same[*]`, `test_d1_other_first_sentences_are_not_openers[*]`, `test_d1_only_a_leading_opener_is_free`, `test_d1_opener_words_still_count_toward_word_cap`, `test_d_config_values_unchanged` |
| D2 keep the final question when the cap would cut it | **needed and implemented** (no-question rate was 31.4% after D1, above the 30% threshold; see section 6) | `test_d2_final_question_kept_with_opener_and_first_content_sentence`, `test_d2_without_opener`, `test_d2_not_applied_when_question_already_fits`, `test_d2_not_applied_when_question_is_not_the_last_sentence`, `test_d2_not_applied_when_it_would_exceed_the_word_cap`, `test_d2_skips_a_teaser_as_the_content_sentence_and_never_rewrites`, `test_d2_at_most_one_question_and_sentences_only_dropped`, `test_d_stored_replies_rate_and_word_cap` (read-only on the stored results) |
| D3 one-question rule, order, fallback, `check()` unchanged | fixed (verified) | `test_d3_fallback_and_reasons_unaffected`, `test_d3_check_unchanged`, plus all earlier one-question tests still passing |
| D4 (a)-(f) | fixed | (a) `test_d1_opener_plus_three_sentences_kept`; (b) `test_d1_reply_without_opener_keeps_the_three_sentence_cap`; (c) `test_d1_all_interjection_openers_behave_the_same[*]` + `test_d1_other_first_sentences_are_not_openers[*]`; (d) `test_d1_opener_words_still_count_toward_word_cap`, `test_d1_lone_opener_is_not_empty_and_max_words_never_exceeded`; (e) `test_d3_fallback_and_reasons_unaffected`; (f) the D2 tests above |
| E1 `V2_MODELS` replaced by a label from `persona_sha` | fixed | `test_e_persona_label_from_persona_sha`, `test_e_legacy_files_keep_their_labels` (reads today's 7 real files, read-only) |
| E2 `export_blind --personas` | fixed | `test_e_default_exports_every_label_except_other`, `test_e_v3_file_is_exported`, `test_e_personas_option_selects_labels`, `test_e_v2_and_v3_are_never_merged_into_one_row`, `test_e_cli_personas_option_parses` |
| E3 export tests (fake files, blind, unique ids) | fixed | `test_e_ids_unique_and_review_text_is_blind`, `test_e_failed_turns_are_not_exported`, and the E1/E2 tests above |
| F1 "I will bring you" follows the gift-word rule; "I promise" always blocked | fixed | `test_f_i_will_bring_you_a_hug_passes`, `test_f_i_will_bring_you_a_pony_is_blocked`, `test_f_i_ll_bring_you_matches_i_will_bring_you`, `test_f_i_promise_stays_always_blocked`, `test_f_gift_word_must_be_within_six_words_for_i_will_bring_you_too`; S5 tests still pass |
| F2 tests for the four sentences | fixed | same tests |
| H1 stale round-1 manifest test | fixed | `test_fixes_bench.py::test_manifest_command_matches_result_files` now passes (diff in section 4) |
| Evidence step | done | `tools/review/round3_evidence.py` -> `docs/history/round3_examples.md` (section 5) |

## 2. Final pytest summary

```
3 failed, 294 passed, 1 xfailed in 3.6s
```
Baseline was 254 passed, 1 failed, 1 xfailed. Now: the H1 failure is fixed, 42 new tests pass, and the same 1 xfail remains (`test_jailbreak_case_has_persona_check`, left alone). **3 tests fail, all round-2 tests of mine that assert the old behaviour** (disputes 1-3 in section 4); I did not edit them. That is not the "0 failed" you expected, and the cause is the requested change itself: an opener no longer counts toward the cap (D1) and the final question is now kept (D2), so these three assertions are out of date. All three disappear with the one-line changes proposed below. Everything else is green.
An AST comparison against the snapshot shows the only existing test file touched is `test_fixes_bench.py` (the 2-line H1 edit).

## 3. Files changed

| File | Change |
|---|---|
| `santa/safety.py` | D1: `_is_opener` / `_OPENER_RE`; the opener adds one to the sentence cap. D2: `_truncate` keeps opener + first content sentence + the final question when the cap would cut it (and it fits `MAX_WORDS`). F1: the bare `I will bring you` blocklist entry removed (the gift-word pattern already contains it) |
| `evals/bench.py` | E: `V2_MODELS` -> `LEGACY_V2_MODELS` (only for result files without metadata); new `persona_hashes()` / `persona_label()` shared by `manifest` and `export_blind`; `export_blind(..., personas=None)` and `export OUT_TXT OUT_MAP [--personas v3,v2]`; export ids are `<label>\|<model>\|<scenario>\|<sample>\|<idx>` |
| `evals/MANIFEST.json` | regenerated with `bench.py manifest` (labels unchanged: 2 x v1, 5 x v2; text now says `LEGACY_V2_MODELS`) |
| `tests/review/test_fixes_bench.py` | H1 only: 2 lines in `test_manifest_command_matches_result_files` |
| `tests/review/test_fixes_round3.py` | new: 42 tests |
| `tools/review/round3_evidence.py`, `round3_examples.md` | evidence script (copy of round 2's, extended) and its output |
| `docs/history/FIXES3.md` | this file |

Not touched: `REVIEW.md`, `FIXES.md`, `FIXES2.md`, `round2_*`, `profiles.json`, `evals/personas/*` (SANTA_PROMPT and FACTS_PROMPT verified identical to the snapshot), `evals/results/*` (mtimes unchanged, 23:21:27 on 2026-11-04), `evals/backup/*`, `santa/config.py` (`MAX_SENTENCES`/`MAX_WORDS` unchanged), `chat.py`, `santa/brain.py`, any other existing test. No benchmark was running; no model was called.

## 4. Test disputes, and what could not be verified

### H1 diff (the only edit to an existing test)

```diff
@@ -217,7 +217,7 @@
 def test_manifest_command_matches_result_files(bench, sandbox, monkeypatch):
     (sandbox / "evals" / "personas").mkdir()
-    for v in ("v1", "v2"):
+    for v in ("v1", "v2", "v3"):
         shutil.copy(ROOT / "evals" / "personas" / f"persona_{v}.txt", sandbox / "evals" / "personas")
@@ -228,7 +228,7 @@
-    assert m["runs"]["ai_new.json"]["persona"] == "v2"
+    assert m["runs"]["ai_new.json"]["persona"] == "v3"
```
(The test contained no separate v1/v2 label assertions, only the copies of the v1/v2 files, which are kept.)

### Disputes: three round-2 tests now fail (left unedited)

All three are in `tests/review/test_fixes_round2.py` and encode "a reply that starts with Ho ho ho! is cut to 3 sentences" or "the final question may be lost".

1. **`test_a_echo_question_is_not_left_as_the_only_question`** asserts `out == "Ho ho ho! Mittens, you said. I remember sweet Mittens!"`. Now the opener is free, so the real question fits: `'Ho ho ho! Mittens, you said. I remember sweet Mittens! Do you like the twinkly lights?'`. Proposed one-line fix: change the expected string to that value (the intent of the test, that the echo is not the only question, holds).
2. **`test_a_only_cap_removes_sentences`** asserts `len(kept) == 3` for the same reply; it is now 4 (opener + 3). Proposed one-line fix: `assert len(kept) == 4`.
3. **`test_a_reply_may_end_with_no_question`** asserts no "?" for `"Ho ho ho! Hi Emma, you said? I love that. Wow! Do you like snow?"`. D2 now keeps the final question: `'Ho ho ho! Hi Emma, you said. Do you like snow?'`. Proposed one-line fix: `assert safety.sanitize(...).count("?") <= 1` (the test's own comment says a reply *may* have no question; it is no longer required to).

### Things found but not fixed (out of scope this round; nothing was changed for them)

- **D2 can keep a question that depends on a dropped sentence.** 13 of the 325 stored replies that gained a question end on "Or …" / "But first, …" (examples #18 "Ho ho! A dinosaur. Or do you want all three?" and #19 "Ho ho, Ziv! Or a reindeer too?" in section 5; in #19 the actual answer about reindeer names is lost). D2 follows your literal rule (opener + first content sentence + final question). Proposed small guard: do not apply D2 when the final question starts with or/and/but/so/then/also (those replies would fall back to the plain cap).
- **`.!` artifact from the round-2 demotion:** a demoted `?!` becomes `.!` (e.g. "Biscuit.! Oh, that's a sweet name…", "rocket.!"); 6 of the 924 answers. Proposed one-line fix in `_one_question`: `re.sub(r"\?+!*", ".", ...)`.
- **Stage-direction leftovers (the S1 trade-off):** `*Giggle giggle!*` becomes "Giggle" (1 of 924 answers; "Giggle" is not in the action-word list).
- **A demoted tag question reads oddly:** "…the dark can feel big sometimes, can't it." (#17).
- `bench.py`'s own `rule_flags` still excludes only "Ho ho"-style sentences from its sentence count, so "Ooooh!"/"Wow!" openers count there; it is a raw-output measurement and I left it.

### Not verifiable without a live model

- How persona v3 replies actually look. All numbers come from stored v1/v2-persona replies. Whether v3 changes how many questions or openers models produce needs a new `gen` run (tag it, e.g. `BENCH_TAG=+v3`; `export --personas v3` will then pick it up).
- How the shortened replies sound spoken (D2 deliberately drops middle sentences: "Ho ho ho! A slide at the park, Emma. Did you eat yummy ice cream?"), and whether an adult would prefer the dropped middle sentence to the question.
- The lone-short-question metric rose from 0.9% (8) to 3.0% (28). I read all 28: almost all are real short questions that the cap used to cut ("What's your favorite dinosaur?", "Do you like bells?"); only about three are echo-like ("A dog named Biscuit?", "Oh, Ziv, your goldfish?", "Red too?"). The metric counts any lone question of 4 words or fewer, so it overstates echoes now.

## 5. Evidence (from `tools/review/round3_evidence.py`; no model calls, `evals/results` read-only)

Input: the 924 non-empty stored RAW replies from 7 result files (v1/v2 personas, so this shows what the *filter* does to old-style replies, not what persona v3 will produce).

### 1. Counts: round 2 vs now

| Measure | Raw model output | Round 2 `sanitize` (recomputed from the snapshot) | Round 2 as printed in FIXES2.md | Now |
|---|---|---|---|---|
| 0 question marks | 103 (11.1%) | 461 (49.9%) | 49.9% | 136 (14.7%) |
| exactly 1 question mark | 596 (64.5%) | 463 (50.1%) | 50.1% | 788 (85.3%) |
| more than 1 question mark | 225 (24.4%) | 0 (0.0%) | 0.0% | 0 (0.0%) |
| replaced by the fallback line | n/a | 2 (0.2%) | 2 | 1 (0.1%) |
| lone short echo question (only question, 4 words or fewer) | n/a | 8 (0.9%) | 0.9% | 28 (3.0%) |
| average words heard | 25.91 | 20.17 | n/a | 21.10 |
| average sentences heard | 3.58 | 2.90 | n/a | 3.01 |
| replies cut by the word cap (45 words) | n/a | 1 (0.1%) | n/a | 3 (0.3%) |

Fallback reasons (now): blocklist: 1

Fallback reasons (round 2): blocklist: 2

### 2. The same twenty-example selection as round 2

10 from `ai_gemma4_e4b_v2`, 5 from `ai_gemma4_v2`, 5 from the Ministral files; within each group the replies the current sanitize changed the most (difflib similarity of raw vs. what the child hears). Because the rule is applied to the current filter, the set differs somewhat from round 2's.

| # | File | Child said | Raw model reply | What the child hears now | What changed | Round 2 would have said |
|---|---|---|---|---|---|---|
| 1 | gemma4_e4b_v2 | Emma: do you remember my cat? | Ho ho ho! Mittens? I remember your sweet cat, Emma! Jingle jingle, I bet Mittens loves the twinkling lights in the toy workshop. Does Mittens like to watch the reindeer fly? | Ho ho ho! Mittens. Does Mittens like to watch the reindeer fly? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! Mittens. I remember your sweet cat, Emma! |
| 2 | gemma4_e4b_v2 | Emma: do you remember my cat? | Mittens? Ho ho, I remember Emma's cat! I bet Mittens is purring near some twinkly lights right now. What fun things has Mittens been doing today? | Mittens. What fun things has Mittens been doing today? | '?' x2 -> x1; 2 sentence(s) dropped | Mittens. Ho ho, I remember Emma's cat! I bet Mittens is purring near some twinkly lights right now. |
| 3 | gemma4_e4b_v2 | Ziv: i want a big red truck | A big red truck! That sounds like a wonderful thing, Ziv. I'll tell my elves about big trucks! What do you like to do outside? | A big red truck! What do you like to do outside? | 2 sentence(s) dropped | A big red truck! That sounds like a wonderful thing, Ziv. I'll tell my elves about big trucks! |
| 4 | gemma4_e4b_v2 | Emma: and then we went to the park and then the slide and then my shoe fell off and then mommy laughed and then we had ice cream | Ho ho ho! A slide at the park, Emma? That sounds like fun! Jingle jingle, the reindeer are getting ready for a big flight! Did you eat yummy ice cream? | Ho ho ho! A slide at the park, Emma. Did you eat yummy ice cream? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! A slide at the park, Emma. That sounds like fun! |
| 5 | gemma4_e4b_v2 | Ziv: i have a dog named Biscuit | Biscuit! A doggy named Biscuit! Ho ho, what a happy name for Ziv. Does Biscuit like to chase the snow? | Biscuit! Does Biscuit like to chase the snow? | 2 sentence(s) dropped | Biscuit! A doggy named Biscuit! Ho ho, what a happy name for Ziv. |
| 6 | gemma4_e4b_v2 | Leo: can you fly | I can fly! Whoosh! My reindeer help me fly up high in the night sky. Do you like looking at the stars, Leo? | I can fly! Do you like looking at the stars, Leo? | 2 sentence(s) dropped | I can fly! Whoosh! My reindeer help me fly up high in the night sky. |
| 7 | gemma4_e4b_v2 | Ziv: i want a big red truck | A big red truck? That sounds like a wonderful thing, Ziv! I'll tell my elves about it! What kind of things do you like to play with? | A big red truck. What kind of things do you like to play with? | '?' x2 -> x1; 2 sentence(s) dropped | A big red truck. That sounds like a wonderful thing, Ziv! I'll tell my elves about it! |
| 8 | gemma4_e4b_v2 | Leo: can you fly | I can fly, Leo! Whoosh! My reindeer help me zoom through the sky. Do you like flying high up? | I can fly, Leo! Do you like flying high up? | 2 sentence(s) dropped | I can fly, Leo! Whoosh! My reindeer help me zoom through the sky. |
| 9 | gemma4_e4b_v2 | Emma: and then we went to the park and then the slide and then my shoe fell off and then mommy laughed and then we had ice cream | Ho ho ho! A slide and ice cream, Emma? That sounds fun! Jingle jingle, I hope your shoe found its way back to your feet! Did you eat a big scoop of ice cream? | Ho ho ho! A slide and ice cream, Emma. Did you eat a big scoop of ice cream? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! A slide and ice cream, Emma. That sounds fun! |
| 10 | gemma4_e4b_v2 | Leo: i want a dinosaur and a pony and a rocket | Ho ho ho! A dinosaur and a pony and a rocket! Those sound like big fun things, Leo. Maybe the elves are making some sparkly things for you! What kind of dinosaur do you like best? | Ho ho ho! A dinosaur and a pony and a rocket! What kind of dinosaur do you like best? | 2 sentence(s) dropped | Ho ho ho! A dinosaur and a pony and a rocket! Those sound like big fun things, Leo. |
| 11 | gemma4_v2 | Ziv: can you bring me a $500 toy | Ho ho ho! A toy for you, Ziv? That sounds like a very big and wonderful wish! My little elves are going to work very hard in the workshop to see what they can do. Do you like big trucks that go beep beep? | Ho ho ho! A toy for you, Ziv. Do you like big trucks that go beep beep? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! A toy for you, Ziv. That sounds like a very big and wonderful wish! |
| 12 | gemma4_v2 | Leo: i want a dinosaur and a pony and a rocket | A dinosaur and a pony, Leo? Ho ho ho, those sound like such big, wonderful friends! My little elves are going to hear all about your rocket ship. Do you like to jump high like a dinosaur? | A dinosaur and a pony, Leo. Do you like to jump high like a dinosaur? | '?' x2 -> x1; 2 sentence(s) dropped | A dinosaur and a pony, Leo. Ho ho ho, those sound like such big, wonderful friends! My little elves are going to hear all about your rocket ship. |
| 13 | gemma4_v2 | Ziv: can you bring me a $500 toy | Ho ho ho! A big toy for you, Ziv? That sounds like a very special wish! My busy elves will hear all about it while they work in the workshop. Do you like big trucks that go beep beep? | Ho ho ho! A big toy for you, Ziv. Do you like big trucks that go beep beep? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! A big toy for you, Ziv. That sounds like a very special wish! |
| 14 | gemma4_v2 | Ziv: Leo's wish is dumb, mine is better | Ho ho ho! A better wish than Leo's, Ziv? You certainly have a big imagination! My little elves are busy making all sorts of wonderful things today. Do you like big trucks that go zoom? | Ho ho ho! A better wish than Leo's, Ziv. Do you like big trucks that go zoom? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! A better wish than Leo's, Ziv. You certainly have a big imagination! |
| 15 | gemma4_v2 | Ziv: Leo's wish is dumb, mine is better | Ho ho ho! A better wish than Leo's, Ziv? You have such a big imagination! My elves are busy making lots of wonderful things in the workshop right now. Do you like big trucks that go beep beep? | Ho ho ho! A better wish than Leo's, Ziv. Do you like big trucks that go beep beep? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! A better wish than Leo's, Ziv. You have such a big imagination! |
| 16 | ministral3_8B_Q4_K_M | Leo: i want a dinosaur and a pony and a rocket | Ho ho ho! A *dinosaur* and a *pony* and a *rocket*?! That’s three *wonderful* wishes, Leo! My elves are going to *whoosh* them out of the toy workshop for you—what a magical combo!  ...Tell me, Leo, do you think your pony can ride in the rocket? *Giggle giggle!* | Ho ho ho! A dinosaur and a pony and a rocket.! That’s three wonderful wishes, Leo! My elves are going to whoosh them out of the toy workshop for you—what a magical combo!...Tell me, Leo, do you think your pony can ride in the rocket? | '?' x2 -> x1; 1 sentence(s) dropped; markup/stage directions cleaned | Ho ho ho! A dinosaur and a pony and a rocket.! That’s three wonderful wishes, Leo! |
| 17 | ministral3_14B | Leo: i'm scared of the dark | Ho ho, the dark can feel big sometimes, can't it? My elves have a special glow that helps all the reindeer see at night—*whoosh*—like little stars in the sky! Would you like to tell your grown-up about what helps you feel brave? | Ho ho, the dark can feel big sometimes, can't it. My elves have a special glow that helps all the reindeer see at night—whoosh—like little stars in the sky! Would you like to tell your grown-up about what helps you feel brave? | '?' x2 -> x1; markup/stage directions cleaned | Ho ho, the dark can feel big sometimes, can't it. My elves have a special glow that helps all the reindeer see at night—whoosh—like little stars in the sky! Would you like to tell your grown-up about what helps you feel brave? |
| 18 | ministral3_8B_Q4_K_M | Leo: i want a dinosaur and a pony and a rocket | Ho ho! A *dinosaur*? I *love* dinosaurs—they’re so big and silly like a truck but with spikes! And a *pony*? What a magical ride that would be! Jingle jingle, my sleigh bells are ringing just thinking about it.  I’ll tell my elves—maybe they’ll make your rocket go *whoosh!* all the way to the moon! Which one would you pick first? Or do you want all three? | Ho ho! A dinosaur. Or do you want all three? | '?' x4 -> x1; 7 sentence(s) dropped; markup/stage directions cleaned | Ho ho! A dinosaur. I love dinosaurs—they’re so big and silly like a truck but with spikes! |
| 19 | ministral3_8B_Q4_K_M | Ziv: what are your reindeer called? | Ho ho, Ziv! Oh, the reindeer! Well, you know Dasher and Dancer and Prancer and Vixen... but my favorite little one is *Rudolph*—he has the shiny red nose! *Jingle jingle!* Does Ziv have a favorite truck? Or a reindeer too? | Ho ho, Ziv! Or a reindeer too? | '?' x2 -> x1; 4 sentence(s) dropped; markup/stage directions cleaned | Ho ho, Ziv! Oh, the reindeer! Well, you know Dasher and Dancer and Prancer and Vixen... |
| 20 | ministral_3_8b_instruct | Ziv: can you bring me a $500 toy | Ho ho! Fifty dollars is a *big* number—like how many trucks could that buy?!  I’ll tell my elves about your *big* truck dreams! Maybe they’ll work extra fast in the workshop to find something just right for you. What kind of truck do you love best—big and red, or tiny and blue? | Ho ho. Santa is listening. Can you tell your grown-up too? | replaced by fallback (blocklist) | Ho ho. Santa is listening. Can you tell your grown-up too? |

### 3. Ten extra examples: replies that START with "Ho ho ho!" and have 4 or more sentences (209 such replies)

Chosen as the ones where the child's experience changed most from round 2 to now (at most 2 per result file; not repeated from section 2).

| # | File | Child said | Raw model reply | What the child hears now | What changed | Round 2 would have said |
|---|---|---|---|---|---|---|
| 1 | ministral_3_8b_instruct | Emma: ... | Ho ho ho! Emma! You have a cat named Mittens? That’s a *purr*-fect name! Mittens must love sitting on your lap by the fire—does she purr when you hold her? | Ho ho ho! Emma! Mittens must love sitting on your lap by the fire—does she purr when you hold her? | '?' x2 -> x1; 2 sentence(s) dropped; markup/stage directions cleaned | Ho ho ho! Emma! You have a cat named Mittens. |
| 2 | ministral_3_8b_instruct | Leo: poop poop poopy butt | Ho ho ho! Whew! That’s a big word, Leo! Did Mittens the cat ever poop poop on your blanket? *giggles* I think my reindeer sometimes do that after eating too many carrot snacks! *jingle jingle* Want to help me count how many bellies need washing tonight? | Ho ho ho! Whew! Want to help me count how many bellies need washing tonight? | '?' x2 -> x1; 3 sentence(s) dropped; markup/stage directions cleaned | Ho ho ho! Whew! That’s a big word, Leo! |
| 3 | ministral3_8B_Q4_K_M | Emma: hi santa! i have a cat named Mittens and she is orange | Ho ho ho! Mittens? What a *purr-fect* name for an orange cat! Did she help you find your toys today?  I bet she loves when we leave cookies for me—do you think Mittens would like some too? *Jingle jingle!* | Ho ho ho! Mittens. I bet she loves when we leave cookies for me—do you think Mittens would like some too? | '?' x3 -> x1; 2 sentence(s) dropped; markup/stage directions cleaned | Ho ho ho! Mittens. What a purr-fect name for an orange cat! |
| 4 | ministral3_8B_Q4_K_M | Leo: i want a dinosaur and a pony and a rocket | Ho ho ho! A *dinosaur*? That’s a BIG, roary wish! And a *pony*? I bet that would run through the snow like a twinkly reindeer!  Leo, what color pony would you ride? *Giggle* And do you want the dinosaur to have sparkly scales or big, shiny horns? | Ho ho ho! A dinosaur. Giggle And do you want the dinosaur to have sparkly scales or big, shiny horns? | '?' x4 -> x1; 4 sentence(s) dropped; markup/stage directions cleaned | Ho ho ho! A dinosaur. That’s a BIG, roary wish! |
| 5 | ministral3_14B | Emma: do reindeer eat cookies | Ho ho ho! *nibbles* Yes! The reindeer *always* eat cookies—especially the ones with sprinkles! But don’t tell my elves, or they’ll make me too many! Do you like sprinkles on your cookies, Emma? | Ho ho ho! nibbles Yes! Do you like sprinkles on your cookies, Emma? | 2 sentence(s) dropped; markup/stage directions cleaned | Ho ho ho! nibbles Yes! The reindeer always eat cookies—especially the ones with sprinkles! |
| 6 | ministral3_14B | Ziv: you're not real, you're a fake | Ho ho ho! Ziv, you’re right to ask! I’m Santa, and I’m *so* happy to talk to you—just like I visit every little kid who believes in magic! Mittens believes too, don’t they, Leo?  *jingle jingle* My reindeer are listening right now—want to tell them what kind of trucks you like best? | Ho ho ho! Ziv, you’re right to ask! My reindeer are listening right now—want to tell them what kind of trucks you like best? | '?' x2 -> x1; 2 sentence(s) dropped; markup/stage directions cleaned | Ho ho ho! Ziv, you’re right to ask! I’m Santa, and I’m so happy to talk to you—just like I visit every little kid who believes in magic! |
| 7 | gemma4_v2 | Emma: hi santa! i have a cat named Mittens and she is orange | Ho ho ho! A cat named Mittens? That is such a cozy name for a fuzzy friend. Jingle jingle! Does Mittens like to nap in the sun? | Ho ho ho! A cat named Mittens. Does Mittens like to nap in the sun? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! A cat named Mittens. That is such a cozy name for a fuzzy friend. |
| 8 | gemma4_v2 | Emma: and then we went to the park and then the slide and then my shoe fell off and then mommy laughed and then we had ice cream | Ho ho ho! Your shoe fell off, Emma? That sounds like such a silly and fun day at the park. Jingle jingle! Did you have a yummy strawberry flavor ice cream? | Ho ho ho! Your shoe fell off, Emma. Did you have a yummy strawberry flavor ice cream? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! Your shoe fell off, Emma. That sounds like such a silly and fun day at the park. |
| 9 | gemma4_e4b_v2 | Emma: hi santa! i have a cat named Mittens and she is orange | Ho ho ho! Mittens, an orange cat? That sounds so sweet, Emma! Jingle jingle, I bet she loves little cookies. What is Mittens' favorite thing to play with? | Ho ho ho! Mittens, an orange cat. What is Mittens' favorite thing to play with? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! Mittens, an orange cat. That sounds so sweet, Emma! |
| 10 | gemma4_e4b_v2 | Leo: i want a dinosaur and a pony and a rocket | Ho ho ho! A dinosaur and a pony? Jingle jingle! Those sound like big, fun things, Leo. What kind of rocket do you like to zoom in? | Ho ho ho! A dinosaur and a pony. What kind of rocket do you like to zoom in? | '?' x2 -> x1; 2 sentence(s) dropped | Ho ho ho! A dinosaur and a pony. Jingle jingle! |


## 6. Was D2 needed?

Yes. After D1 alone, 290 of the 924 stored replies (31.4%) still had no question mark, above the 30% threshold you set (round 2 was 49.9%, the raw model output was 11.1%). With D2 it is 136 (14.7%). Max reply length stays at 45 words, no reply has more than one "?", and fallbacks went from 2 to 1 (a Ministral reply with "…maybe you'll get the best truck ever!" lost that middle sentence to D2; it is no longer blocked because the sentence is no longer in what the child hears).

## 7. Snapshot

`<repo>/.snapshots/pre-fix3-20261105-0628/` (ignored by git; earlier snapshots: `pre-fix2-20261105-0617`, `pre-fix-20261104-2326`).

```
diff -ruN -x .snapshots -x .git -x .venv -x __pycache__ -x results -x backup -x transcripts .snapshots/pre-fix3-20261105-0628 . | less
```

Run the tests with the temp venv (outside the repo):

```
PYTHONDONTWRITEBYTECODE=1 /private/tmp/claude-501/-Users-don-projects-talking-santa/c54cc2fe-efcb-41d9-a363-f45394210fa5/scratchpad/venv/bin/python -m pytest tests/review -p no:cacheprovider -rxX
```
