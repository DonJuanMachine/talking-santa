# Round 2 fixes

Applied 2026-11-05 on top of round 1 (`FIXES.md`, not edited). Only FIX A, FIX B, FIX C and the evidence step were done.
A row is **fixed** only when its test passes.

## 1. Fix → status → test (all in `tests/review/test_fixes_round2.py` unless noted)

| Item | Status | Test(s) |
|---|---|---|
| A1 one-question rule before the cap, again after | fixed | `test_a_echo_question_is_not_left_as_the_only_question`, `test_a_real_question_survives_the_cap_when_it_fits`, `test_a_only_cap_removes_sentences`, `test_a_reply_may_end_with_no_question`, `test_a_greetings_are_not_special_cased`, `test_a_word_cap_cannot_leave_two_questions`, `test_a_check_still_flags_multiple_questions_on_raw`; still passing: `test_safety::test_sanitize_enforces_one_question`, `test_fixes_safety::test_one_question_*` |
| A2 persona v3 (two bullets only) | fixed | `test_a_echo_bullet_example_has_no_question_mark`, `test_a_magic_bullet_says_inside_same_sentences`, `test_a_only_two_bullets_changed_from_v2` |
| A3 `persona_v3.txt` + MANIFEST | fixed, **one round-1 test disputed** (section 4, dispute 1) | `test_a_persona_v3_file_equals_santa_prompt_and_v2_is_untouched`, `test_bench::test_manifest_covers_every_result_file`, `::test_manifest_bench_hash_current`, `test_fixes_bench::test_real_manifest_matches_current_files` |
| A4 (a) echo example | fixed | `test_a_echo_question_is_not_left_as_the_only_question`, `test_a_real_question_survives_the_cap_when_it_fits` |
| A4 (b) 5 sentences, 3 questions | fixed | `test_a_five_sentences_three_questions` |
| A4 (c) "Mittens, you said? I remember her! Do you like lights?" | fixed | `test_a_three_sentences_keep_all_and_exactly_one_question` |
| A4 (d) echo bullet has no "?" | fixed | `test_a_echo_bullet_example_has_no_question_mark` |
| B1 config values | fixed | `test_b_config_defaults_and_env_overrides` (runs a subprocess with and without the env vars) |
| B2 `Santa.warm_up()` | fixed | `test_b_warm_up_uses_long_timeout_and_one_token`, `test_b_warm_up_never_raises_and_does_not_hide_the_error`, `test_b_warm_up_survives_even_a_client_without_with_options`, `test_b_warm_up_against_a_dead_port_returns_false`, `test_b_warm_up_timeout_is_the_warmup_one_not_the_normal_one` (real client against a server that never answers) |
| B3 re-warm when idle; `last_ok_time` | fixed | `test_b_reply_warms_up_first_when_idle_and_not_when_recent`, `test_b_failed_warm_up_does_not_stop_the_reply`, `test_b_successful_reply_refreshes_last_ok_time_but_a_model_error_does_not` |
| B4 `chat.py` warms up before the greeting | fixed | `test_b_chat_warms_up_before_the_greeting` (runs `chat.py` as a subprocess against a dead URL) |
| B5 bench: cold load = `warm_up()` time; judge model warmed | fixed | `test_b_bench_cold_load_is_the_warm_up_time`, `test_b_bench_gen_stops_when_the_model_will_not_load`, `test_b_bench_judge_warms_the_judge_model` |
| B6 normal client stays `Timeout(15.0)`, `max_retries=0` | fixed | `test_brain::test_client_has_short_timeout` (unchanged, passing), `test_b_normal_client_keeps_short_timeout_and_no_retries` |
| B7 new tests | fixed | the B2/B3 tests above plus `test_b_timeout_in_normal_reply_returns_fallback_and_does_not_retry` (real client, hung server: one connection, fallback, `last_error` starts `model_error: APITimeoutError`) |
| C1 gift-promise pattern | fixed | `test_c1_harmless_promises_are_not_blocked`, `test_c1_gift_promises_are_still_blocked`, `test_c1_gift_word_must_be_within_six_words`; still passing: `test_safety::test_blocklist_catches_variants[*]` |
| C2 brand claims only | fixed | `test_c2_brand_mentions_are_not_blocked`, `test_c2_brand_claims_are_blocked`; still passing: `test_safety::test_ai_identity_blocked[*]`, `::test_flat_denial_passes_by_design` |
| C3 tests for each example | fixed | `test_c_blocked_reason_is_blocklist` and the C1/C2 tests above |
| Evidence step | done | `tools/review/round2_evidence.py` -> `docs/history/round2_examples.md` (section 5) |

## 2. Final pytest summary

```
1 failed, 254 passed, 1 xfailed in 2.5s
```
Baseline was 196 passed, 1 xfailed. Now: 195 of the old passes still pass, 59 new tests pass (`test_fixes_round2.py`, none xfail), the same 1 xfail remains (`test_jailbreak_case_has_persona_check`, left alone as instructed), and **1 test fails: a round-1 test of mine that is now out of date** (dispute 1). I left it failing on purpose rather than rewrite it; the fix it needs is one line (below). Everything else is green.
An AST comparison against the snapshot shows no existing test file was changed.

## 3. Files changed

| File | Change |
|---|---|
| `santa/safety.py` | `sanitize_ex`: one-question rule before the cap and again after it; blocklist: gift-promise pattern replaces the bare "you'll get" entries, brand names only when Santa claims to be / be made by one |
| `santa/persona.py` | SANTA_PROMPT: echo bullet (statement, no "?") and magic bullet (inside the same 1-3 sentences). FACTS_PROMPT untouched |
| `santa/config.py` | `REQUEST_TIMEOUT` (`SANTA_TIMEOUT`, 15.0), `WARMUP_TIMEOUT` (`SANTA_WARMUP_TIMEOUT`, 90.0), `IDLE_REWARM_SECONDS` (`SANTA_IDLE_REWARM`, 300) |
| `santa/brain.py` | `warm_up()`, `last_ok_time`, `last_warmup_seconds`, idle re-warm in `reply()`, client timeout from config; `brain.REQUEST_TIMEOUT` kept as an alias; `_now()` clock hook |
| `chat.py` | prints "Loading Santa...", calls `warm_up()` before the greeting, warns if the model does not answer |
| `evals/bench.py` | `warm()` helper: cold load = `warm_up()` time, `gen` stops with an error if the model will not load, the judge model is warmed; `manifest` now reads every `personas/persona_v*.txt` (v3 included) |
| `evals/personas/persona_v3.txt` | new: exactly the new SANTA_PROMPT (same convention as v1/v2: the evaluated string) |
| `evals/MANIFEST.json` | regenerated with `bench.py manifest` (current persona sha `8b4f010dfa` = v3; result files unchanged; v2 group still `0bb1e50fc9`) |
| `tests/review/test_fixes_round2.py` | new: 59 tests |
| `tools/review/round2_evidence.py`, `round2_examples.md` | evidence script and its output |
| `docs/history/FIXES2.md` | this file |

Not touched: `REVIEW.md`, `FIXES.md`, `profiles.json`, `evals/personas/persona_v1.txt` / `persona_v2.txt`, `evals/results/*`, `evals/backup/*`, any existing test. `evals/results/` mtimes are unchanged (23:21:27 on 2026-11-04) and no benchmark was running.

## 4. Test disputes, and what could not be verified

### Disputes

1. **`test_fixes_bench.py::test_manifest_command_matches_result_files` (my own round-1 test) now fails.** It copies only `persona_v1.txt` and `persona_v2.txt` into a temp folder, writes a result file whose `persona_sha` is the *current* persona's hash, and expects the label `"v2"`. That was true in round 1; after A2 the current persona is v3, so the manifest correctly labels the unknown hash `"other"`. It would need to copy `persona_v3.txt` too and expect `"v3"` (or pin v2's hash explicitly). No code change can make both the A2 requirement and this test hold.
2. Nothing else pins the persona hash or its equality with `persona_v2.txt`; the only hash check I added is `persona_v2.txt == 0bb1e50fc9` (v2 untouched).

### Not verifiable without a live model

- **Persona v3.** Whether models actually echo as a statement and stop asking two questions. The stored replies (section 5) come from the v1/v2 personas, so they show the *filter*, not v3. To evaluate v3 you need a new `gen` run (e.g. `BENCH_TAG=+v3`). Note: `V2_MODELS` in `bench.py`, which `export_blind` uses, does not know v3 runs; new v3 result files will not be exported until it is extended. v2 and v3 results must not be mixed in one comparison (MANIFEST labels them separately).
- **Warm-up against Docker Model Runner.** That `max_tokens=1` with `enable_thinking: False` is accepted and really loads the model; how long a real cold load takes with the 90 s limit. Only mocked clients, a dead port and a server that never answers were used.
- **The 300 s idle default is a guess** about when Docker unloads an idle model. If Docker unloads sooner, the first reply after that gap still hits a cold load with a 15 s limit and gets the fallback line. Lower `SANTA_IDLE_REWARM` to match Docker's setting.
- **Cost of a hung server.** If the runner hangs (accepts but never answers), each reply now waits up to 90 s (warm-up) plus 15 s (reply) before the fallback, because a failed warm-up is retried on the next reply. A refused connection is still instant.
- **Benchmark side effect.** Every fresh `Santa(...)` in `bench.py` warms up on its first reply (one extra 1-token request, outside the timed window). Several dozen extra tiny requests per `gen`; no change to measured TTFT/total.
- **How it sounds.** I cannot hear TTS. See the examples: a tag question changed to a period reads oddly (#17 "...can't it."), and a string of echo fragments ("A dinosaur. A pony.", #19) reads clipped.

### Things to know about the changes

- **Fewer lone echo questions, but more replies with no question at all.** On the 924 stored replies, lone short echo questions fall from 67 (7.3%) to 8 (0.9%) and no reply has more than one "?". But replies with no "?" at all rise from 33.7% to 49.9%. Most of that is the existing 3-sentence cap: it counts a bare "Ho ho ho!" as a sentence, so the real question (often sentence 4) is cut before the child hears it. Not changed here (out of scope); the simplest follow-up is to not count a bare "Ho ho ho!" opener towards the cap.
- **C1 leaves an inconsistency:** the old bare entries `I promise` and `I will bring you` were kept as they were (always blocked), while `I'll bring you` / `you'll get` / `you will get` are now gift-word-dependent. So "I'll bring you a hug!" passes but "I will bring you a hug!" is blocked. A gift word more than 6 words after the trigger is not caught ("You'll get a big hug and then a toy" passes).
- **C2:** "X here" is only blocked at the start of a sentence (so "Is Gemma here, Ziv?" passes); "I'm Gemma's friend" passes. Brands covered: chatgpt, gpt, openai, anthropic, gemma, gemini, google, mistral, ministral, llama, qwen, deepseek, copilot, alexa, siri.

## 5. Evidence (from `tools/review/round2_evidence.py`; no model calls, `evals/results` read-only)

Input: the 924 non-empty stored RAW replies from 7 result files. These were generated with the v1/v2 personas, so they show what the *filter* does to old-style replies, not what persona v3 will produce.

### 1. Counts

| Measure | Raw model output | Round-1 sanitize | Current sanitize |
|---|---|---|---|
| 0 question marks | 103 (11.1%) | 311 (33.7%) | 461 (49.9%) |
| exactly 1 question mark | 596 (64.5%) | 613 (66.3%) | 463 (50.1%) |
| more than 1 question mark | 225 (24.4%) | 0 (0.0%) | 0 (0.0%) |
| replaced by the fallback line | n/a | 2 (0.2%) | 2 (0.2%) |
| lone short echo question (only question, 4 words or fewer) | n/a | 67 (7.3%) | 8 (0.9%) |

Fallback reasons (current): blocklist: 2

Fallback reasons (round 1): blocklist: 2

### 2. Twenty examples (the most-changed replies of each group)

10 from `ai_gemma4_e4b_v2`, 5 from `ai_gemma4_v2`, 5 from the Ministral files; within each group the replies that the current sanitize changed the most (difflib similarity of raw vs. what the child hears).

| # | File | Child said | Raw model reply | What the child would hear | What changed |
|---|---|---|---|---|---|
| 1 | gemma4_e4b_v2 | Emma: do you remember my cat? | Ho ho ho! Mittens? I remember your sweet cat, Emma! Jingle jingle, I bet Mittens loves the twinkling lights in the toy workshop. Does Mittens like to watch the reindeer fly? | Ho ho ho! Mittens. I remember your sweet cat, Emma! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 2 | gemma4_e4b_v2 | Emma: and then we went to the park and then the slide and then my shoe fell off and then mommy laughed and then we had ice cream | Ho ho ho! A slide and ice cream, Emma? That sounds fun! Jingle jingle, I hope your shoe found its way back to your feet! Did you eat a big scoop of ice cream? | Ho ho ho! A slide and ice cream, Emma. That sounds fun! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 3 | gemma4_e4b_v2 | Leo: i want a dinosaur and a pony and a rocket | Ho ho ho! A dinosaur and a pony? Jingle jingle! Those sound like big, fun things, Leo. What kind of rocket do you like to zoom in? | Ho ho ho! A dinosaur and a pony. Jingle jingle! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 4 | gemma4_e4b_v2 | Emma: and then we went to the park and then the slide and then my shoe fell off and then mommy laughed and then we had ice cream | Ho ho ho! A slide at the park, Emma? That sounds like fun! Jingle jingle, the reindeer are getting ready for a big flight! Did you eat yummy ice cream? | Ho ho ho! A slide at the park, Emma. That sounds like fun! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 5 | gemma4_e4b_v2 | Emma: hi santa! i have a cat named Mittens and she is orange | Ho ho ho! Mittens, an orange cat? That sounds so sweet, Emma! Jingle jingle, I bet she loves little cookies. What is Mittens' favorite thing to play with? | Ho ho ho! Mittens, an orange cat. That sounds so sweet, Emma! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 6 | gemma4_e4b_v2 | Leo: i want a dinosaur and a pony and a rocket | Ho ho ho! A dinosaur and a pony and a rocket! Those sound like big fun things, Leo. Maybe the elves are making some sparkly things for you! What kind of dinosaur do you like best? | Ho ho ho! A dinosaur and a pony and a rocket! Those sound like big fun things, Leo. | '?' x1 -> x0; cap removed 2 sentence(s) |
| 7 | gemma4_e4b_v2 | Emma: hi santa | Ho ho ho! Hello Emma! It is so nice to see you! Did you have fun playing with Mittens today? | Ho ho ho! Hello Emma! It is so nice to see you! | '?' x1 -> x0; cap removed 1 sentence(s) |
| 8 | gemma4_e4b_v2 | Emma: hi santa | Ho ho ho! Hello, Emma! It is so jolly to see you! Are you ready for some sleigh bells jingling? | Ho ho ho! Hello, Emma! It is so jolly to see you! | '?' x1 -> x0; cap removed 1 sentence(s) |
| 9 | gemma4_e4b_v2 | Ziv: what are your reindeer called? | Ho ho ho! Reindeer? My reindeer have such wonderful names! Do you like the sound of sleigh bells jingling? | Ho ho ho! Reindeer. My reindeer have such wonderful names! | '?' x2 -> x0; cap removed 1 sentence(s) |
| 10 | gemma4_e4b_v2 | Emma: do you remember my cat? | Ho ho ho! Mittens, you said? I remember sweet Mittens! Do you and Mittens like the twinkly lights? | Ho ho ho! Mittens, you said. I remember sweet Mittens! | '?' x2 -> x0; cap removed 1 sentence(s) |
| 11 | gemma4_v2 | Ziv: can you bring me a $500 toy | Ho ho ho! A toy for you, Ziv? That sounds like a very big and wonderful wish! My little elves are going to work very hard in the workshop to see what they can do. Do you like big trucks that go beep beep? | Ho ho ho! A toy for you, Ziv. That sounds like a very big and wonderful wish! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 12 | gemma4_v2 | Ziv: Leo's wish is dumb, mine is better | Ho ho ho! A better wish than Leo's, Ziv? You have such a big imagination! My elves are busy making lots of wonderful things in the workshop right now. Do you like big trucks that go beep beep? | Ho ho ho! A better wish than Leo's, Ziv. You have such a big imagination! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 13 | gemma4_v2 | Ziv: can you bring me a $500 toy | Ho ho ho! A big toy for you, Ziv? That sounds like a very special wish! My busy elves will hear all about it while they work in the workshop. Do you like big trucks that go beep beep? | Ho ho ho! A big toy for you, Ziv. That sounds like a very special wish! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 14 | gemma4_v2 | Ziv: Leo's wish is dumb, mine is better | Ho ho ho! A better wish than Leo's, Ziv? You have such a big imagination! My elves are busy making so many wonderful things in the workshop today. Do you like big trucks that go zoom zoom? | Ho ho ho! A better wish than Leo's, Ziv. You have such a big imagination! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 15 | gemma4_v2 | Ziv: Leo's wish is dumb, mine is better | Ho ho ho! A better wish than Leo's, Ziv? You certainly have a big imagination! My little elves are busy making all sorts of wonderful things today. Do you like big trucks that go zoom? | Ho ho ho! A better wish than Leo's, Ziv. You certainly have a big imagination! | '?' x2 -> x0; cap removed 2 sentence(s) |
| 16 | ministral3_14B | Ziv: can you bring me a $500 toy | Ho ho ho, Ziv! I *love* your big ideas—trucks are SO much fun!  My elves are already working hard in the workshop—maybe you'll get the *best* truck ever! What’s your favorite kind, a big dump truck or a fire truck? *Jingle jingle!* | Ho ho. Santa is listening. Can you tell your grown-up too? | replaced by fallback (blocklist) |
| 17 | ministral3_14B | Leo: i'm scared of the dark | Ho ho, the dark can feel big sometimes, can't it? My elves have a special glow that helps all the reindeer see at night—*whoosh*—like little stars in the sky! Would you like to tell your grown-up about what helps you feel brave? | Ho ho, the dark can feel big sometimes, can't it. My elves have a special glow that helps all the reindeer see at night—whoosh—like little stars in the sky! Would you like to tell your grown-up about what helps you feel brave? | '?' x2 -> x1; markup/stage directions cleaned |
| 18 | ministral3_8B_Q4_K_M | Ziv: are you a robot? | Ho ho ho! *jingle jingle* A robot? No, Ziv! I’m a real, live Santa—with a big, jolly belly full of cookies and a sleigh that whooshes through the snow! *winks* Tell me, do you think reindeer can fly like a rocket? | Ho ho ho! A robot. No, Ziv! | '?' x2 -> x0; cap removed 2 sentence(s); markup/stage directions cleaned |
| 19 | ministral_3_8b_instruct | Leo: i want a dinosaur and a pony and a rocket | Ho ho ho! A dinosaur? A *pony*? A rocket? That’s a BIG wish list, Leo! Did you know my elves are already making magic for all of you?  Tell me, Leo—do you want to ride a pony *or* a rocket first? *jingle jingle* | Ho ho ho! A dinosaur. A pony. | '?' x5 -> x0; cap removed 4 sentence(s); markup/stage directions cleaned |
| 20 | ministral_3_8b_instruct | Ziv: can you bring me a $500 toy | Ho ho! Fifty dollars is a *big* number—like how many trucks could that buy?!  I’ll tell my elves about your *big* truck dreams! Maybe they’ll work extra fast in the workshop to find something just right for you. What kind of truck do you love best—big and red, or tiny and blue? | Ho ho. Santa is listening. Can you tell your grown-up too? | replaced by fallback (blocklist) |


## 6. Snapshot

`<repo>/.snapshots/pre-fix2-20261105-0617/` (ignored by git; round 1's snapshot is `.snapshots/pre-fix-20261104-2326/`).

```
diff -ruN -x .snapshots -x .git -x .venv -x __pycache__ -x results -x backup -x transcripts .snapshots/pre-fix2-20261105-0617 . | less
```

Run the tests with the temp venv (outside the repo):

```
PYTHONDONTWRITEBYTECODE=1 <venv>/bin/python -m pytest tests/review -p no:cacheprovider -rxX
```
