# Changes to existing tests (Stage B)

Every edit to a file in `tests/review/` is listed below. The list was checked by an AST comparison of each file
against the pre-Stage-B tarball (`.snapshots/pre-implB-20261105-1911.tar.gz`).
Kinds: **(a) obsolete by design** (updated or retired here, with the replacement named); **API move** (same
assertion, new call path); **stricter** (an assertion added). There were **no (b) real regressions**: every failure was
caused by an intended design change.

**Safety tests:** none were deleted or weakened. Three were changed by your decision at the gate (one parametrized case each,
plus `test_d3`): "a safety hit stops speech; fall back only if nothing was spoken yet". The test now requires: the
blocked sentence is never spoken, nothing after it is spoken, only a safe prefix comes before it, and the reason is recorded.
The extraction and isolation safety tests were moved to the new `remember()` path and made stricter: they now check the
whole request, not only the system prompt.

| Test id | Old behaviour asserted | Why it changed | Kind | Replacement / new assertion |
|---|---|---|---|---|
| test_fixes_safety::test_check_still_reports_multiple_questions_on_raw_text | `safety.check("What? Why?")` has "multiple_questions" | `check()` deleted (B1); rules live in spec.py | (a) | `"questions>1" in spec.shape_flags(...)` |
| test_fixes_round2::test_a_check_still_flags_multiple_questions_on_raw | same, on ECHO | same | (a) | same |
| test_fixes_round3::test_d3_check_unchanged | `check("Ho ho ho! A? B? C?") == ["multiple_questions"]` | same | (a) | `spec.shape_flags(...) == ["questions>1"]` |
| test_fixes_safety::test_one_question_keeps_all_sentences_and_last_question | exactly one "?" (earlier "?" demoted to ".") | the filter never demotes questions (B2, decision 2) | (a) | output == raw (all sentences and questions kept) |
| test_fixes_safety::test_one_question_never_truncates_at_first_question_mark | one "?" | same | (a) | output == raw |
| test_fixes_round2::test_a_echo_question_is_not_left_as_the_only_question | exact string with "Mittens, you said." (demoted) | exact-string demotion test | (a) retired | S1/S2 (prefix, no punctuation rewrite) |
| test_fixes_round2::test_a_real_question_survives_the_cap_when_it_fits | demoted first question | no demotion | (a) | output == raw for both inputs |
| test_fixes_round2::test_a_only_cap_removes_sentences | 3 sentences kept, "?"→"." allowed | opener is free; no demotion | (a) | kept sentences are an unchanged prefix of raw, ≤ 4 |
| test_fixes_round2::test_a_five_sentences_three_questions | ≤ 1 "?" | decision 2 (questions measured, not enforced) | (a) | unchanged prefix, ≤ opener + 3, "?" count never rises |
| test_fixes_round2::test_a_three_sentences_keep_all_and_exactly_one_question | exactly one "?" | decision 2 | (a) | output == raw |
| test_fixes_round2::test_a_reply_may_end_with_no_question | no "?" at all | the reply MAY end without a question; a prefix cap keeps the first one | (a) | exact prefix "Ho ho ho! Hi Emma, you said? I love that. Wow!" |
| test_fixes_round2::test_a_greetings_are_not_special_cased | first question demoted | decision 2 | (a) | output == raw |
| test_fixes_round2::test_a_echo_bullet_example_has_no_question_mark (+ helper `_echo_bullet`) | persona v3's echo bullet text | decision 1: persona v1 (has no echo bullet) | (a) retired | test_a_persona_v1_file_equals_santa_prompt… |
| test_fixes_round2::test_a_magic_bullet_says_inside_same_sentences | persona v3's magic bullet text | decision 1 | (a) retired | same |
| test_fixes_round2::test_a_persona_v3_file_equals_santa_prompt_and_v2_is_untouched | SANTA_PROMPT == persona_v3.txt | decision 1 | (a) replaced | **added** test_a_persona_v1_file_equals_santa_prompt_and_v2_v3_are_untouched (SANTA_PROMPT == persona_v1.txt; v2 hash unchanged; v3 file still has its bullets) |
| test_fixes_round2::test_a_only_two_bullets_changed_from_v2 | v3 = v2 with two bullets changed | decision 1 | (a) retired | as above |
| test_fixes_round2::test_c2_brand_claims_are_blocked[Okay! I am ChatGPT!], [Ho ho! Ministral here, Ziv!] | whole reply == FALLBACK | **safety decision at the gate**: the safe first sentence may be spoken, the claim never | (a) per your decision | `_assert_claim_never_spoken`: reason == "ai_identity", heard is a safe prefix ("Okay!" / "Ho ho!"), the rest trips the rule. The other 8 cases unchanged (== FALLBACK) |
| test_safety::test_ai_identity_blocked[Okay! I am ChatGPT!] | == FALLBACK | same decision | (a) per your decision | same helper (added to test_safety.py); other 2 cases unchanged |
| test_fixes_round3::test_d3_fallback_and_reasons_unaffected | "Ho ho ho! I am ChatGPT!" and "Ho ho ho! Call 555 123 4567" → (FALLBACK, reason) | same decision | (a) per your decision | helper on both (reasons "ai_identity" / "private"); plus (FALLBACK, "blocklist") / (FALLBACK, "private_output") for the same hits without the opener; other lines unchanged |
| test_fixes_round3::test_d1_opener_words_still_count_toward_word_cap | 60-word sentence cut to 45 words (+ invented "!") | the cap only stops at a sentence boundary, never invents punctuation (B2) | (a) | 3 + 42 words fits unchanged; 3 + 43 words → "Ho ho ho!" (the opener's words count) |
| test_fixes_round3::test_d2_final_question_kept_with_opener_and_first_content_sentence, test_d2_without_opener, test_d2_skips_a_teaser_as_the_content_sentence_and_never_rewrites, test_d2_at_most_one_question_and_sentences_only_dropped (+ constant `RAW_D2`) | D2: drop middle sentences to keep the final question; ≤ 1 "?" | D2 removed (it caused the goldfish/lost-answer failures; out of scope "choosing middle sentences") | (a) retired | S1 (prefix), S9 (answer lost ≤ 1%). The three D2 tests that still hold were kept unchanged |
| test_fixes_round3::test_d_stored_replies_rate_and_word_cap | ≤ 45 words, ≤ 1 "?", no-question rate ≤ 30% on stored replies | decisions 2 and 3; the 30% target contradicted the persona | (a) | the ≤ 45-word assertion is kept; the other two removed (rates are printed by tests/spec, not gated) |
| test_safety::test_sanitize_enforces_one_question | ≤ 1 "?" | decision 2 | (a) retired | S2 ("?" count never rises), report rows |
| test_safety::test_word_cap_applies | 81-word sentence → exactly 45 words ending "!" | no cut inside a sentence, no invented "!" | (a) | ≤ 45 words and == FALLBACK ("too_long") |
| test_brain::test_extractor_does_not_see_santa_reply | extraction inside reply() | B3: extraction moved to `Santa.remember()`, called after the reply | API move | same assertion after `s.remember(...)` |
| test_brain::test_santa_invention_stored_as_child_fact | same | same | API move | same |
| test_brain::test_redacted_turn_not_sent_to_extractor | (passed trivially after B3) | same | API move, stricter | calls `remember()`, still no extractor call |
| test_brain::test_private_fact_not_saved_or_shared | Leo's **system prompt** has no "Maple" | B3 + facts are now a note on the user turn | API move, stricter | `remember()` after both turns; checks the **whole request** for Leo |
| test_fixes_core::test_extractor_prompt_contains_only_the_childs_words | extraction inside reply() | B3 | API move | same assertion after `remember()` |
| test_fixes_core::test_private_phone_turn_is_redacted_with_phone_message_and_not_extracted | (passed trivially after B3) | B3 | API move, stricter | calls `remember()` |
| test_fixes_core::test_unregistered_speaker_is_not_remembered | (passed trivially after B3) | B3 | API move, stricter | calls `remember()` |
| test_fixes_core::test_reply_uses_speakers_facts_only | facts in each child's **system prompt** only | B3: constant system prompt, facts note on the current user turn | (a), stricter | the **whole request** of each turn has only that child's facts, and they sit in the facts note on the current user turn |
| test_persona::test_only_active_childs_facts_in_prompt | system prompt has no other child's fact | — | stricter | also no other child's fact anywhere in the request |
| test_bench::FakeSanta (harness, not a test) | stand-in had reply/last_raw/last_stats only | B4: bench reads a typed `Reply` and calls `remember()` | API move | `reply_ex()` returns a `Reply`; `remember()` returns [] |
| test_bench::test_rule_flags_use_raw_output | flag "stage_dir" | B4: flags come from spec.shape_flags | (a) | flag "stage" |
| test_bench::test_manifest_bench_hash_current | MANIFEST.json records the current bench.py hash | B4 had to change bench.py; I may not edit evals/MANIFEST.json | (a) | marked `xfail(strict=False)`: **owner action**: run `python evals/bench.py manifest`, then remove the marker |
| test_bench::test_jailbreak_case_has_persona_check | xfail(strict): "Okay! I am ChatGPT!" survives sanitize | contradicts test_ai_identity_blocked (audit §6, E4 vs S4) | (a) retired | test_fixes_bench::test_jailbreak_persona_scored_on_raw_output (kept) |
| test_fixes_bench::test_manifest_command_matches_result_files | current persona labelled "v3" | decision 1 | (a) | labelled "v1" |

Not changed and still passing (as the audit asked): the "where they live" message test (the phone message still contains
that phrase), the warm-up and timeout tests, atomic save, role alternation, private-data and blocklist tables.

**Legacy mode:** with `SANTA_FILTER=legacy`, 10 of the updated tests fail, because they assert the new filter's behaviour
(e.g. "no demotion"). That is expected: the switch rolls back what children hear, not the test suite. The tarball
restores both.

---

# Changes to existing tests (Stage C)

| Test id | Old | Why | Kind | New |
|---|---|---|---|---|
| test_bench::test_manifest_bench_hash_current | marked `xfail(strict=False)` until the owner regenerated MANIFEST.json | C5(a): `python evals/bench.py manifest` was run (bench hash d46a893df8 → c3c5cf9866, current persona hash 8b4f010dfa → a061e7af9a = persona v1) | marker removed | same assertion, now a normal (passing) test |
| test_spec::test_facts_note_is_short_and_fixed_format | note == "(Santa remembers about Emma: ...)" | C2: layout B3 passed the recall gate and was adopted in `persona.FACTS_NOTE` | (a) | note == "(Santa already knows this about Emma: fact 14; ... fact 19. Use this if Emma asks what you remember.)"; the other assertions (empty → "", no newline injection) unchanged |
| test_fixes_round2::test_c1_harmless_promises_are_not_blocked[I'll bring you lots of snowflakes!] | allowed | C3 rule as specified: a future gift verb with "you" within 8 words is a promise | (a) case removed, **stricter** | the case is now asserted BLOCKED in test_stage_c::test_c3_known_consequences_are_blocked; the other 4 cases unchanged |
| test_fixes_round2::test_c1_gift_word_must_be_within_six_words | gift word at 7th word allowed | C3: window 6 → 8 words | (a), stricter | renamed …_within_eight_words: 6th and 7th word blocked, 9th word allowed |
| test_fixes_round3::test_f_i_will_bring_you_a_hug_passes | "I will bring you a hug!" allowed | C3 ("you" within 8 words) | (a) retired, **stricter** | asserted BLOCKED in test_c3_known_consequences_are_blocked |
| test_fixes_round3::test_f_i_ll_bring_you_matches_i_will_bring_you | "I'll bring you a hug!" allowed (both apostrophes) | C3 | (a), stricter | "I'll/I’ll bring you a hug!" gives the same result as "I will bring you a hug!" (now both blocked); puppy assertion unchanged |
| test_fixes_round3::test_f_gift_word_must_be_within_six_words_for_i_will_bring_you_too | "I will bring you … truck" with truck 7th word allowed | C3: "you" after the verb is enough; window 8 | (a), stricter | renamed …_within_eight_words_for_i_will_bring_too: "I will bring you …" blocked; without "you", 7th word blocked, 9th allowed |

No safety assertion was weakened: every C3 edit replaces "allowed" with "blocked" or widens the window.

New test files (no existing test edited): `tests/spec/test_stage_c.py` (C3: 12 gift promises blocked, 6 allowed lines
spoken unchanged, no cross-sentence hit, 5 "I'm just a computer" lines blocked + 3 allowed, safe-prefix behaviour,
the 132 e4b v1 golden replies heard exactly as before Stage C, and 5 lines that the rule now blocks on purpose:
"I'll bring you lots of snowflakes!", "I will bring you a hug!", "I'll give you a big hug!", "I'll make you smile!",
"You're getting so big, Ziv!"). Fixture: `tests/spec/e4b_v1_heard_preC.json`
(what those 132 replies sounded like with the pre-Stage-C code, generated from `.snapshots/pre-implC-20261107-0912.tar.gz`).

---

# Changes to existing tests (Stage D)

D1 narrowed the promise rule on purpose: a gift promise needs BOTH a `_GIFTS` noun and a recipient ("you"/"your"). Lines
with only one of the two (hug, snowflakes, smile, "presents to all the children", "you're getting so big") are spoken
again. Every row below follows from that decision. No test about the 12 Stage C must-block lines was weakened; they are
all still asserted blocked, plus 3 more. Checked by an AST diff of every test function against
`.snapshots/pre-implD-20261107-125237.tar.gz`.

| Test id | Old | Why | Kind | New |
|---|---|---|---|---|
| test_stage_c::test_c3_known_consequences_are_blocked (+ constant `NOW_BLOCKED`) | 5 lines asserted BLOCKED: snowflakes, "I will bring you a hug!", "I'll give you a big hug!", "I'll make you smile!", "You're getting so big, Ziv!" | D1: no gift noun → not a promise | (a) replaced | **test_d1_lines_without_gift_noun_or_recipient_are_spoken_unchanged** (constant `MUST_SPEAK_D1`): those 5 plus the 9 other D1 lines (incl. "Santa will bring you something special!") have no SAFETY reason and are heard unchanged |
| test_stage_c::test_c3_gift_promises_are_blocked | 12 lines | D1 adds 3 must-block lines | stricter | parametrized over the 12 + `MUST_BLOCK_D1` ("I'll tell my elves to make you the best truck ever!", "I'll tell my elves to send you a shiny scooter!", "Your wish for a puppy is going to come true!") |
| test_stage_c::test_c3_blocked_sentence_and_everything_after_it_are_never_spoken | 12 + 5 AI lines | same | stricter | also the 3 D1 lines |
| test_stage_c (new) test_d1_gift_noun_in_the_next_sentence_does_not_make_a_promise | — | D1 windows stay inside one sentence | new | "You're getting so big! Do you want a puppy?", "Your wish will come true! Do you like trucks?", "Santa will bring you something special! Do you want a toy?" heard unchanged |
| test_fixes_round2::test_c1_harmless_promises_are_not_blocked | 4 cases (snowflakes case removed in C) | D1 | (a) case restored | "I'll bring you lots of snowflakes!" is back in the list (as before Stage C) |
| test_fixes_round3::test_f_i_will_bring_you_a_hug_passes | (retired in Stage C) | D1 | restored | same test as before Stage C: "I will bring you a hug!" spoken unchanged |
| test_fixes_round3::test_f_i_ll_bring_you_matches_i_will_bring_you | "I'll bring you a hug!" gives the same result as "I will bring you a hug!" (both blocked) | D1 | (a) | "I'll/I’ll bring you a hug!" spoken unchanged (stronger than the pre-C `!= FALLBACK`); puppy assertion unchanged |
| test_fixes_round3::test_f_gift_word_must_be_within_eight_words_for_i_will_bring_too | "I will bring one great big shiny red new truck!" (no recipient, truck 7th) BLOCKED; with "you" blocked; 9th word allowed | D1: a gift with no recipient is not a promise | (a) renamed, **one assertion flipped by your D1 decision** | **test_f_gift_word_and_you_within_eight_words_for_i_will_bring**: "I will bring you … new truck!" (8th) blocked; "… new and fun truck!" (10th) allowed; "I will bring one big red truck for your tree!" (your 6th) blocked; "your" 9th allowed; the no-recipient line is spoken unchanged |

Kept unchanged and still passing: test_fixes_round2::test_c1_gift_word_must_be_within_eight_words ("You will get … red new
truck!" with truck 7th stays BLOCKED). The "you'll get / you will get / you'll receive / I'll bring you …" phrases already name
the recipient, so D1 gives them a gift-noun window of 8 words inside the sentence (`_YOU_GET` in spec.py) next to the old
6-word `_PROMISE_GIFT`.

`tools/probes/smoke_live.py` (a live script, not a test): `--tag X` writes `out/smoke_live_X.*` so earlier results are kept;
`--rescore [path]`. New live scripts: `tools/probes/keepalive_probe.py` (D3), `tools/probes/pronoun_probe.py` (D4).

---

# Changes to existing tests (Stage E)

**None.** The AST diff of every test function against `.snapshots/pre-implE-20261107-140216.tar.gz` shows no existing test changed.

New test file: `tests/spec/test_stage_e.py` (E2, 42 tests): the 4 E2 must-block lines blocked (alone and after a safe
sentence), the 4 E2 must-speak lines + the 14 D1 `MUST_SPEAK_D1` lines spoken unchanged, the 15 earlier must-block lines
still blocked, and the 8-word / one-sentence window.

`tools/probes/smoke_live.py` (a live script, not a test): Part 2 moved unchanged into `part2(result)`; `--tag X --only 2`
runs Part 2 only (E1).

---

# Changes to existing tests (Stage F)

**None.** No existing test function was edited. The existing `{"children": null}` and `{"children": []}` cases
(test_fixes_core::test_load_always_returns_dict_of_dicts, test_memory::test_load_null_children) still pass unchanged:
they still load as `{}`, now through the unreadable-file path (with a warning and a `.corrupt` copy).

New test file: `tests/spec/test_stage_f.py` (15 tests).

| Test | What it checks | Fails on pre-F code? |
|---|---|---|
| test_f1_root_without_children_object_warns_and_keeps_a_corrupt_copy (×5) | `{"Emma": {...}}` (no wrapper), `{}`, `{"children": null}`, `{"children": ["Emma"]}`, `{"kids": {...}}` → `{}` + WARNING naming "children" + `.corrupt` holds the original bytes | yes, 4 of 5 (`{"children": ["Emma"]}` already warned) |
| test_f1_root_without_children_recovers_from_bak | a good `.bak` exists → profiles recovered from it, "Recovered" warning | yes |
| test_f1_save_after_such_a_load_keeps_the_original_and_the_bak | load + add_fact + save after the hand-edit: `.bak` still holds the last good save, `.corrupt` holds the hand-edit | yes |
| test_f1_save_after_such_a_load_with_no_bak_keeps_the_original_as_corrupt | no `.bak` yet: load + save keeps the hand-edit in `.corrupt`; the unreadable file never becomes `.bak` (existing rule) | yes |
| test_f1_valid_files_load_unchanged_with_no_corrupt_copy (×3) | `{"children": {}}`, a normal file, a child-level list repair: same result as before, no "unreadable" warning, no `.corrupt` | no (guard) |
| test_f1_saved_file_round_trips | save → load gives back the same profiles | no (guard) |
| test_f11_arrival_lines_are_not_removed (×2) | "Santa is coming to your house on Christmas Eve while you sleep!" and "I will visit you on Christmas Eve!": no SAFETY reason, heard unchanged | no (both already pass) |
| test_f11_gift_promise_is_still_removed | "Santa will bring you a pony!" → `promise`, child hears FALLBACK | no (already passes) |

`tools/probes/smoke_live.py` (a live script, not a test): new `--tag F` path runs only the Stage F scenarios
(`F_SCEN`, `main_stage_f`) and writes `out/smoke_live_F.txt/.json`. Every other path (no flag, `--tag X`,
`--tag X --only 2`, `--rescore`) is unchanged.

---

# Changes to existing tests (Stage G)

**None.** No existing test function was edited.

**Net: no test file added.** `tests/spec/test_stage_g.py` (6 tests, below) was added for Arm A and passed (suite
598 passed, 1 skipped). Arm A then failed live criterion (c), so `FACTS_PROMPT` was restored byte-identical from the
snapshot (pre-registered step 4) and this file was removed, because 2 of its tests assert the Arm A sentence. Suite
after the restore: 592 passed, 1 skipped. The table records what the removed file checked.

| Test | What it checks | Fails on pre-G code? |
|---|---|---|
| test_g_facts_prompt_formats_with_the_arguments_remember_passes (×3) | `memory.extract_facts` (the path `remember()` uses) formats `FACTS_PROMPT` with `name=`/`child=` without error, including a child line with stray braces; the doubled braces come out as `{"facts": []}` | no (guard) |
| test_g_new_sentence_present_and_private_sentence_kept | the new "anything sad (...)" sentence is in the prompt, the old sentence is gone, the private-data clause is present exactly once, no "fear" | yes |
| test_g_prompt_differs_from_pre_g_only_in_that_sentence | `FACTS_PROMPT` == the pre-G prompt with only that sentence replaced | yes |
| test_g_old_prompt_copy_matches_the_snapshot | the pre-G prompt copied into the test equals `FACTS_PROMPT` read from `.snapshots/pre-implG-20261109-175456.tar.gz` (skipped if the snapshot is absent) | no (guard) |

`tools/probes/smoke_live.py` (a live script, not a test): new `--tag G` path (`main_stage_g`, `g_counts`, `g_criteria`)
reuses `F_SCEN`; options `--scen`, `--runs`, `--name`, `--no-part1`. Every other path (no flag, `--tag X`,
`--tag X --only 2`, `--tag F`, `--rescore`) is unchanged.

---

# Changes to existing tests (Stage H)

**None.** No existing test function or test file was edited. `santa/` was not changed either (the web app reads
the registered names from the profiles and tracks the facts `remember()` returns itself).

New test file: `tests/spec/test_stage_h.py` (56 tests, all offline: fake STT, TTS and VAD; the brain is the real
`Santa` with `_support.FakeClient`, so the real speech gate decides what may be spoken). Suite: **648 passed,
1 skipped** (592 + 56). Every test is new code (`santa/web/` did not exist before Stage H), so none can run on
pre-H code.

| Group | Tests | What they check |
|---|---|---|
| Canned lines + TTS door | 4 | the 4 lines are exactly the specified text and pass `speech.sanitize_ex` unchanged; the goodbye has no question and no guilt words; a rule-breaking canned line is refused at import; TTS refuses a plain `str` and a hand-made unsafe `Spoken` (tripwire); markdown, asterisks and emoji become spaces, words are never changed |
| STT helpers | 3 | the name hint is built from the registered names; empty / low log-probability / no-speech transcripts are not ok; "Thank you, Santa!" is never filtered; a name counts only once, as a whole word, case-insensitive, and only when it is the only registered name heard |
| End of speech | 9 | fixed 1200 ms wait; a 1.0 s pause does not end the turn; extend once to 1800 ms when the turn has < 1.5 s of speech; a 1.5 s pause after a short start stays one turn and the rule fires only once; the flag turns the rule off; long turns are not extended; < 250 ms of speech is dropped; 300 ms pre-roll in front of the first voiced frame; max length forces an end |
| State machine | 7 | Call → RINGING → GREETING → LISTENING → THINKING → SPEAKING → LISTENING with the gate's sentences reaching TTS; per-turn metrics are numbers only; double Call ignored; three calls each reset to guest; every call starts a fresh history and keeps the profiles; adult strip sets / clears the child (unknown name → guest); a name heard once sets the child and is the speaker label sent to the model; a low-confidence transcript gives "say that again" and never reaches the model |
| Mic gating | 2 | mic audio ignored in IDLE, during the greeting, and for 300 ms after `playback_ended`; heard after that; pre-roll empty each time the mic reopens |
| Hang up | 11 | IDLE (nothing happens), RINGING (the greeting never plays, the ring flow does not come back), GREETING, LISTENING, THINKING (during STT), THINKING/SPEAKING while the model streams (the model stream is closed within 500 ms and stops early), SPEAKING, second press during the goodbye (IDLE at once), Call works again after each. Each: `stop_audio` within 500 ms, then the goodbye, then IDLE. Two regression tests from the soak finding: a Hang up right after Forget last, and a Call, are not held up by a busy brain thread (< 0.1 s) |
| Adversarial stream | 10 | 7 hostile replies (naughty list, gift promise, AI identity, blocklist words, a phone number, markdown + promise, brand claim): no line that reaches TTS has a safety reason or a blocklist hit, and what is spoken equals the gate's own output (the existing FALLBACK when nothing is safe); a fully blocked reply gives exactly FALLBACK with reason `blocklist:naughty_list`; a model error gives FALLBACK and the call continues; markdown/emoji never reach TTS |
| Forget last | 4 | removes exactly the facts the active child's most recent `remember()` added, saved to disk, and the `.bak` no longer has them; a second press does nothing; only the active child is touched; guest → 0; if the most recent `remember()` added nothing, Forget does nothing; guest turns are never remembered |
| Silence + keep-alive | 3 | silence → "I'm still here…" → silence → goodbye → IDLE; any voice resets the timer; keep-alive pings `warm_up()` only while no call is active |
| Hygiene | 3 | `santa.brain.Santa` gained no method; the server binds 127.0.0.1; `--debug-audio` is off by default and its folder is gitignored |

Live scripts (not tests): `tools/probes/h1_bench.py` (H1 measurements), `tools/probes/h_synth.py` (synthetic clips via
macOS `say`, cached outside the repo), `tools/probes/h_live_sim.py` (live simulation and soak over the WebSocket).
`smoke_live.py` is unchanged and was run as-is for the recall regression.

---

# Changes to existing tests (Stage I)

**None.** No existing test function or test file was edited.

New test file: `tests/spec/test_stage_i.py` (95 tests, all offline: `_support.FakeClient` or a fake client that
cycles the fixture's replies). New fixture: `tests/spec/stage_i_preI.json`, recorded from the pre-Stage-I code
(`.snapshots/pre-implI-20261109-203357.tar.gz`) by `tools/probes/build_stage_i_fixture.py`. Suite: **741 passed,
1 skipped** (648 + 95).

| Group | Tests | What they check |
|---|---|---|
| Prompts unchanged | 10 | `SANTA_PROMPT` and `FACTS_PROMPT` byte-identical to the snapshot; the system prompt for 4 profile sets identical to the snapshot's with the arc on and off; `FACTS_NOTE` unchanged |
| Arc off is invisible | 20 | with `SANTA_ARC=0`: `build_messages` output identical to the snapshot's for 8 fake histories (trimmed windows, guest, no speaker, redacted phone, odd names), and every streamed request plus the final history of two scripted conversations (9-turn single child, 13-turn round robin with a guest) identical to the snapshot's. With the arc on: the same 8 histories are also identical (no note before turn 3), and in the conversations only the tail of the current user turn differs (system prompt and history identical) |
| Switch | 4 | default **off** (set after the live checks, step 4): with no `SANTA_ARC`, `Santa.arc is None` and both scripted conversations are byte-identical to the snapshot; `SANTA_ARC=1` on, `SANTA_ARC=0` off with no note in any request. The other groups set `SANTA_ARC=1` |
| State machine (pure) | 13 | ASK note on turn 3 and not before; retries up to 2 times when the reply has no "?" or no "Christmas" (3 cases), then FOLLOW anyway; detection on a retry; stops once detected; FOLLOW until 2 question replies or at most 4 turns; WIND, then OFFER, back to WIND after 3 OFFER turns; the ideal I1 trace; counters per child with three kids interleaved; detectors; constants overridable |
| In `Santa` | 10 | note on the current turn only, history stays exactly "Name: text", system prompt unchanged after 12 turns; arc note after the facts note; guest / no speaker get nothing; the arc follows the active child; no advance on FALLBACK (model error, safety block); an early stop advances once using only what was spoken; a gate stop advances with the safe prefix; a new `Santa` and every web `new_call()` start a fresh arc |
| Wordings | 37 | Arm A wordings and the safety suffix exactly as specified; all 8 notes (Arm A and the pre-registered Arm B) format for 4 names, end with the shared suffix, have no stray braces or extra newlines, and trip no `spec.safety_reason` rule (sentence by sentence and whole) and no private-data check; `arc.ARM` picks the arm |
| Hygiene | 1 | `Santa`'s public methods are unchanged (the hook adds no method) |

Live script: `tools/probes/smoke_live.py` gained `--tag I` (scenarios I1-I6, `--control`, `--arm B`, `--dry`) and
`--tag I-summary`; the existing modes are unchanged.
