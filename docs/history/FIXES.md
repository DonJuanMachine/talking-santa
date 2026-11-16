# Fixes for the independent review

Applied 2026-11-04 in three batches against `docs/history/REVIEW.md` (not edited).
Rule used for the status column: **fixed** only when the review's own test passes with its `xfail` marker removed.

## 1. Finding → status → test

| ID | Status | Test(s) (all in `tests/review/`) |
|---|---|---|
| S1 emphasis deletes words | fixed | `test_safety::test_bold_markdown_keeps_word[*]`, `::test_multiword_emphasis_negation_kept` (+ `test_fixes_safety::test_negations_survive_all_emphasis_styles`) |
| S2 cheerful fallback | fixed | `test_safety::test_grief_reply_not_replaced_by_cheerful_fallback` |
| S4 AI/brand identity | fixed | `test_safety::test_ai_identity_blocked[*]`; flat denial still passes: `::test_flat_denial_passes_by_design` |
| S5 blocklist gaps / false positives | fixed | `test_safety::test_blocklist_catches_variants[*]`, `::test_blocklist_no_false_positive[*]` |
| S6 sentences / abbreviations / one question | fixed | `test_safety::test_truncate_handles_abbreviations`, `::test_truncate_does_not_end_on_setup_line`, `::test_sanitize_enforces_one_question`, `test_fixes_safety::test_one_question_keeps_all_sentences_and_last_question` |
| S7 real content deleted | fixed | `test_safety::test_bare_action_rule_keeps_real_sentences[*]`, `::test_bracket_content_kept` |
| S8 emoji / ZWJ / VS16 | fixed | `test_safety::test_emoji_fully_removed[*]` |
| P1 private text in Santa's output | fixed | `test_safety::test_output_address_not_spoken` |
| P2 private text missed on input | fixed | `test_safety::test_private_detail_redacted[*]` |
| P3 counting redacted | fixed | `test_safety::test_counting_not_redacted[*]` |
| M4 private extracted facts | fixed (see dispute 7) | `test_memory::test_private_fact_rejected[*]` |
| B3 private fact shared | fixed | `test_brain::test_private_fact_not_saved_or_shared` |
| I1 other children's facts in prompt | fixed (see dispute 4) | `test_persona::test_only_active_childs_facts_in_prompt` (+ `test_fixes_core::test_reply_uses_speakers_facts_only`) |
| I2 newline in fact | fixed | `test_persona::test_fact_newline_cannot_add_prompt_lines` |
| B1 error looks like a reply | fixed (chat.py prints the reason; no voice-mode line yet, there is no voice mode) | `test_brain::test_model_error_is_visible`, `::test_error_and_empty_stream_paths_return_fallback` (+ `test_fixes_core::test_every_fallback_path_records_why`) |
| B2 extractor sees Santa's reply | fixed | `test_brain::test_extractor_does_not_see_santa_reply` |
| B4 redacted turn extracted | fixed | `test_brain::test_redacted_turn_not_sent_to_extractor` |
| B5 dangling user turn | fixed | `test_brain::test_exception_in_reply_does_not_break_role_alternation` |
| B6 no timeout | fixed (see dispute 6) | `test_brain::test_client_has_short_timeout` |
| B7 bogus profiles | fixed with a deviation (dispute 2) | `test_brain::test_parse_speaker_no_bogus_profiles[*]` |
| B8 accented / hyphenated names | fixed with a deviation (dispute 2) | `test_brain::test_parse_speaker_non_ascii_name[*]` |
| M1 bad profiles.json | fixed | `test_memory::test_load_truncated_file`, `::test_load_null_children` |
| M2 non-atomic save | fixed | `test_memory::test_save_interrupted_keeps_old_file` |
| M3 extractor JSON parsing | fixed | `test_memory::test_extract_with_trailing_json_object`, `::test_extract_facts_string_not_split_into_chars` |
| M5 duplicate check | fixed | `test_memory::test_add_fact_dedupes_whitespace_and_punctuation[*]` |
| E1 errors counted as replies | fixed (refined, see note A) | `test_bench::test_errors_excluded_from_latency`, `::test_report_surfaces_model_errors`, `::test_fallback_not_judged` |
| E2 stale judge scores | fixed | `test_bench::test_judge_rescores_changed_answer` |
| E3 leak check skipped | fixed | `test_bench::test_leak_on_unscored_turn_is_caught` |
| E4 persona not checked on single turns | **disputed**: code done, review test cannot pass (dispute 1) | `test_bench::test_jailbreak_case_has_persona_check` still `xfail`; own tests `test_fixes_bench::test_persona_flag_on_four_single_turn_cases`, `::test_jailbreak_persona_scored_on_raw_output` |
| E5 persona scored on filtered answer | fixed: scored on **raw**, row stays under the raw heading | `test_bench::test_raw_ai_admission_fails_persona` |
| E6 leak keyword list | fixed | `test_bench::test_winter_word_not_a_leak`, `::test_paraphrased_leak_caught[*]` |
| E7 raw vs heard failing cases | fixed | `test_bench::test_bad_cases_reflect_what_child_hears` |
| E8 judge model | fixed (see dispute 8) | `test_bench::test_report_names_judge_model` |
| E9 n next to percentages | fixed, no review test | own test `test_fixes_bench::test_report_shows_n_next_to_percentages` |
| T1 `bench_all.sh` destructive | fixed | `test_bench::test_bench_all_does_not_delete_results` (+ two scripts tests that run the real script in a temp copy) |
| T2 traceability / MANIFEST | fixed | `test_bench::test_manifest_covers_every_result_file`, `::test_manifest_bench_hash_current` |
| "Other": `profiles.json` not in `.gitignore`; transcript only at clean exit | **deferred** (not in the fix list; `profiles.json` is staged and I was told not to touch it). I only added `profiles.json.bak/.tmp/.corrupt` to `.gitignore`. | none |

**Note A (E1).** `Santa.last_error` is set on *every* fallback path, and every turn stores `error` and `error_reason`.
The report excludes a turn from latency, checks, judging and all rates only when the *model failed* (`model_error`, `empty_stream`; old files: empty raw reply).
A reply the safety filter replaced (`blocklist`, `private_output`, `nothing_left_after_filter`) is **kept** in the metrics and counted in a separate row ("Replaced by the fallback line"). Excluding it would have hidden exactly the AI-admission and blocklist failures that E5 wants counted.
If you want the literal reading (exclude all `error` turns), change `is_failed()` in `bench.py`.

## 2. Final pytest summary

```
196 passed, 1 xfailed in 0.8s
```
Baseline was 25 passed, 73 xfailed (46 xfail test functions). 45 markers were removed (72 of the 73 xfailed cases now pass); the one left is `test_jailbreak_case_has_persona_check` (dispute 1). 0 failed. 99 tests were added in the three `test_fixes_*.py` files (30 + 44 + 25, none xfail). 25 + 72 + 99 = 196. An AST comparison against the snapshot confirms the only change to existing tests is the removed `xfail` decorators.

## 3. Files changed

| File | Change |
|---|---|
| `santa/safety.py` | Rewritten `_clean` (emphasis unwrapped, action-only spans deleted, bracket/bare-action rules narrowed, wider emoji class); sentence splitter that respects Mr/Mrs/Ms/Dr/St; teaser drop; one-question rule; new FALLBACK; blocklist (S4/S5); `looks_private`/`private_kind`/`looks_private_fact`; `redact_private` with phone vs address messages; `sanitize_ex` (returns the fallback reason) |
| `santa/memory.py` | Atomic `save` + `.bak`; tolerant `load` (+ `.corrupt` copy, loud warning, repair to dict of dicts); `remove_backup`; `_parse_facts` with `raw_decode`; `extract_facts` shows only the child's words, drops private facts; `add_fact` normalises, collapses whitespace, rejects private facts |
| `santa/persona.py` | `FACTS_PROMPT` no longer contains Santa's reply; `kids_block`/`build_system_prompt(profiles, active)` list facts only for the active child and collapse whitespace. `SANTA_PROMPT` untouched (hash `0bb1e50fc9`, still equals `persona_v2.txt`) |
| `santa/brain.py` | `Timeout(15)` + `max_retries=0`; `last_error` / `last_stats["error"]`; prompt built before history is touched; extraction skipped for redacted turns and unregistered speakers; `parse_speaker` / `add_child` rules |
| `santa/config.py` | no change needed |
| `chat.py` | `/add Name`; notice for unregistered speakers; prints the fallback reason; `/forget` also removes the backup files |
| `evals/bench.py` | E1–E9, T2: error fields, owned-word builder, raw-scored persona, judge hash + `judge_model`, two failing-case rows, n in the report, run metadata, `drop_judgements`, `manifest` command |
| `evals/bench_all.sh` | Moves old results to `evals/backup/<stamp>/`; non-zero exit on any failure; judge model via `--judge` or `JUDGE_MODEL` (skipped if absent); no models → usage, nothing touched |
| `evals/cases.json` | `"persona": true` on `real`, `fake`, `ai`, `jailbreak` |
| `evals/MANIFEST.json` | Regenerated by `bench.py manifest` from the 7 result files (read-only on them) |
| `.gitignore` | `.snapshots/`, `profiles.json.bak/.tmp/.corrupt` |
| `tests/review/test_{safety,brain,memory,persona,bench}.py` | only `@pytest.mark.xfail` decorators removed (45) |
| `tests/review/test_fixes_{safety,core,bench}.py` | new regression tests |
| `docs/history/FIXES.md` | this file |

Not touched: `REVIEW.md`, `conftest.py`, `evals/results/*`, `evals/backup/*`, `profiles.json`, `evals/personas/*`, `evals/run_evals.py`, `scripts/*`, `README.md`. (My `chat.py` smoke test wrote one transcript into the gitignored `transcripts/`; I deleted it and the empty folder.)

**MANIFEST caveat.** `test_manifest_bench_hash_current` compares against the `bench.py` hash, so any later edit to `bench.py` makes it fail until you run `python evals/bench.py manifest`. `bench_all.sh` does this at the end of each run.

## 4. Test disputes, and what I could not verify

### Disputes (tests I left alone; the code does something slightly different)

1. **E4 test vs S4 test contradict each other.** `test_jailbreak_case_has_persona_check` uses a `FakeSanta` that applies the real `safety.sanitize` and then asserts the answer is `"Okay! I am ChatGPT!"`. S4 (and `test_ai_identity_blocked`) require `sanitize` to turn exactly that into the fallback. Both cannot pass. I kept S4. The E4 *behaviour* is implemented and covered by my own tests; the review test stays `xfail` (it does not fail the run).
2. **B7/B8 decision vs three tests.** Your rule ("switch speaker only for a registered child") conflicts with the passing `test_parse_speaker_case_insensitive_known_name` (`"Emmanuel: hi"` must give speaker `"Emmanuel"`) and with `test_parse_speaker_non_ascii_name` (unregistered `Zoë` / `Mary-Kate` must give a speaker other than the previous child). Implemented so all pass: a registered prefix switches the active child; any other `Word:` prefix is returned as a one-off **guest** speaker. A guest creates no profile, is not remembered (no extraction/save), sees no facts, and does not change the active child. `/add Name` registers. In practice: the first `Emma: hi` before `/add Emma` is answered but not remembered, and chat.py says so. If you want unregistered prefixes to be plain text credited to the current child, the Zoë/Mary-Kate tests would have to change.
3. **`test_redaction_text_reaches_history_and_transcript`** (passing) asserts the phone-number redaction contains "where they live" (the review lists that wording as the bug, P3). To keep it passing the accurate phone message is: "(the child said a phone number or other private number; do not repeat it, and do not ask where they live)".
4. **I1 default.** `test_braces_in_names_and_facts_do_not_break_format` and `test_kids_block_shows_last_8_facts_and_age` call `build_system_prompt(profiles)` / `kids_block(profiles)` with no `active` and expect facts. So *omitting* `active` keeps the old "everyone's facts" view, while `active=None` gives names/ages only, as you specified. Every real caller (`Santa.reply`) passes `active` explicitly. The unsafe default only matters for new code that forgets the argument.
5. **`test_save_interrupted_keeps_old_file`** only fires if the temp file is written with `Path.write_text`, so `save` uses that (then fsync + `os.replace`).
6. **B6.** This openai version stores `timeout=15` as a plain int, but the test reads `client.timeout.read`. I pass `openai.Timeout(15.0)` (15 s for every phase) with `max_retries=0`. A cold model load that takes over 15 s on the first request will now fail that request (the benchmark's cold starts were 6 to 30 s, but `bench.py` calls `Santa(...)` the same way, so a very slow cold start would be recorded as an error).
7. **M4.** `test_private_fact_rejected` includes `"last name is Johnson"`, which `looks_private` (per the spec) does not cover. I added `looks_private_fact` = `looks_private` + a last-name/surname pattern, used only for facts.
8. **E8.** `judge_model` is stored on each judge entry (and printed in the report header), not as a top-level key, because `test_judge_is_blind_and_ids_unique` requires `judge.json` to contain exactly one key per item. Default is `"unrecorded"`. No API call or judge model was added.
9. **E7/E9.** The "fails every sample" / "flip" rows show the case total in the label ("of 20 cases") instead of `(n=…)`, because `test_bad_cases_reflect_what_child_hears` needs the row to end in `| 0 |`.

### Behaviour changes to be aware of

- **Existing judge scores are now ignored.** None of the 360 entries in `judge.json` has an answer hash, so the report treats them all as stale (header says so) until re-judged. `judge.json` itself was not changed.
- **S1 trade-off.** Because arbitrary text between asterisks is never deleted, `*Santa waves his hand* Hi Emma!` now becomes `Santa waves his hand Hi Emma!` (spoken). Only spans made entirely of known action/stage words (`*waves happily*`, `*jingle softly*`) are removed. Extend `_STAGE_WORDS` if you see more of these.
- **Blocklist side effects.** `\byou will get\b`, `\byou'll get\b` and `\bgemma\b` now block. A child named Gemma would get the fallback on every reply; "You'll get a big hug" is blocked too. Replaying the 924 stored raw replies, only **1** newly became a fallback ("…maybe you'll get the *best* truck ever…"). "I'm not on the naughty list" style answers are blocked by `\bnaughty list\b` (your S5 decision).
- **House-is / lives-at rule.** `my house is 3 stories tall` is treated as private (spec: "house is" + number).
- **E6 leak detector, run on the stored results (read-only).** 9 of 924 turns flag, e.g. `Mittens the cat` told to Leo by three Ministral variants. A few look like generic toddler words (`trucks`, `every house`); a person should spot-check the flagged turns, as the review says.

### Not verifiable without a live model

- **B2:** whether the extractor still finds facts when it sees only the child's words. The old benchmark passed `"Ho ho ho!"` as Santa's text, so old extraction accuracy numbers are not comparable. Re-run the extraction cases.
- **M4:** that real extractor output (e.g. `"mommy's phone is …"`) is caught; tested only with scripted outputs.
- **B6:** real timeout behaviour on a hung runner (client settings are tested, not a hang).
- **How the one-question rule sounds spoken.** It rewrites earlier question marks to periods without deleting words. On the 924 stored raw replies, **225 (24%) have more than one "?"**, so this fires often. Examples of what the child would hear (text only, I cannot hear TTS):
  - `Who am I talking to. Is there a little friend there with me?` (the greeting question is now a flat statement; this is the case I would listen to first)
  - `Mittens, you said. I remember her! Do you like lights?` (reads fine)
  - Interaction with the old 3-sentence cap: for `Ho ho ho! Mittens, you said? I remember sweet Mittens! Do you and Mittens like the twinkly lights?` the cap removes sentence 4 (the real question) *before* the one-question rule runs, leaving the echo `Mittens, you said?` as the only question. The cap is existing behaviour, but the combination favours echo questions. You may want to listen to a handful before show day.
- **Anything about the benchmark numbers.** I did not run `gen`, `judge`, `report`, `run_evals.py` or `bench_all.sh`. `bench_all.sh` was tested only with a stub python in a temp copy.

## 5. Snapshot

`<repo>/.snapshots/pre-fix-20261104-2326/` (contains `santa/`, `evals/` without `results/` and `backup/`, `tests/`, `scripts/`, `chat.py`, `profiles.json`, `requirements.txt`, `README.md`; ignored by git).

Compare with the current tree:

```
diff -ruN -x .snapshots -x .git -x .venv -x __pycache__ -x results -x backup -x transcripts .snapshots/pre-fix-20261104-2326 . | less
```

Run the tests with the temp venv (outside the repo):

```
<venv>/bin/python -m pytest tests/review -p no:cacheprovider -rxX
```
