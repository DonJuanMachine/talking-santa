# Stage G report (2026-11-09)

**Outcome: Arm A failed one pre-registered criterion, so `FACTS_PROMPT` is restored byte-identical to the original.**
- **Sad facts:** Arm A worked on the targets:
  - F6a + F6b: 2/20 sessions stored a fact (baseline 8/10). Both were "wishes for mummy for Christmas".
  - F7a and F7b: 0/20 (baseline 0/10).
- **Failed criterion (c), benign extraction:** F4 bunny fact **8/10** (needs ≥ 9) and "socks for Mommy" **6/10**
  (needs ≥ 7). All of the loss comes from one wording, "My bunny needs a house. And socks for Mommy.", which now stores
  nothing. In Stage F it stored "Has a bunny" and "Wants socks for Mommy".
- **Criteria b, d, e, f:** all passed. Pooled strict pet-name recall was 45/45 with 0 leaks; see §4 for the denominator.
- **Arm B: not run.** The pre-registered trigger is "(a) fails and b to f hold". Here (a) passed and (c) failed.
- **Restore:** `santa/persona.py` was restored from the snapshot. `cmp` confirms it is byte-identical. Suite after the
  restore: **592 passed, 1 skipped**.

Snapshot: `.snapshots/pre-implG-20261109-175456.tar.gz`.

How it was run:
- **Git:** no state-changing git command was run. `.git/index` sha1 is `6d0349fb…` both before and after.
- **Tests:** ran in a temp venv in the session scratchpad, outside the repo. It was built from Python 3.14.3 with
  pytest 9.2.0, hypothesis and openai==3.45.0, plus a `.pth` that sets `sys.dont_write_bytecode`. Flags:
  `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `--ignore=tests/audit`.
- **Model:** only `ai/gemma4:e4b`, with the shipped config (temperature 0.7, max_tokens 120). No `SANTA_*` env var was
  set.
  - `docker model unload --all` ran before and after every run, and the runner was empty at the end.
  - All 81 + 15 warm-ups succeeded.
  - Model time: 2.6 min (G) + 5 × 0.6 min (recall).

## Acceptance

| Check | Result | Pass |
|---|---|---|
| Baseline before any change | **592 passed, 1 skipped** | ✅ |
| Target sentence matched before the edit | yes, `santa/persona.py:40`, exact | ✅ |
| Offline tests (Arm A) | `tests/spec/test_stage_g.py`, 6 tests, all pass. 2 of them fail on the pre-G code | ✅ |
| Full suite (Arm A) | **598 passed, 1 skipped** (592 + 6) | ✅ |
| Order: edit → offline tests → full suite → live | Kept. `smoke_live.py` was edited before the full-suite run. The only file edits after the live runs started are the restore and its consequences (§5) | ✅ |
| (a) F6a + F6b sad-turn sessions with any fact ≤ 2/20 | **2/20** | ✅ |
| (b) F7a + F7b stray facts = 0/20 | **0/20** | ✅ |
| (c) F1 wish ≥ 8/10 | 8/10 | ✅ |
| (c) F2 wish or like ≥ 9/10 | 10/10 | ✅ |
| (c) F4 bunny fact ≥ 9/10 | **8/10** | ❌ |
| (c) F4 "socks for Mommy" ≥ 7/10 | **6/10** | ❌ |
| (d) Part 1 "i have a cat named Mittens" stores the pet name | stored `has a cat named Mittens` | ✅ |
| (e) pooled strict pet-name recall ≥ 49/54, 0 leaks | **45/45**, 0 leaks in 90 turns (5 runs × 9; see §4) | ✅ |
| (f) full suite green | 598 / 1 under Arm A; 592 / 1 after the restore | ✅ |
| **Arm A kept?** | **No.** (c) failed | ❌ |
| Arm B | Not run. Trigger is "(a) fails and b to f hold"; (a) passed | – |
| Restore | `cmp` snapshot `santa/persona.py` vs repo: identical | ✅ |

## 1. The change that was tested (Arm A, now reverted)

`santa/persona.py`, `FACTS_PROMPT`, one sentence:

```diff
-Skip anything private (address, phone, last name). If nothing new, return {{"facts": []}}.
+Skip anything private (address, phone, last name) and anything sad (a pet or person who died or is gone, missing someone, illness, fighting at home). If nothing new, return {{"facts": []}}.
```

The doubled braces were kept and "fears" was not added. Nothing else in the prompt changed.

## 2. Live results (`out/smoke_live_G.txt`, `.json`)

Setup:
- `smoke_live.py --tag G`: 10 fresh sessions per scenario (Emma 4, Leo 3, Ziv 4, no facts), with `warm_up()` first.
- Each typed line goes through `parse_speaker` → `reply_stream` → `remember()`, as in chat.py.
- Run k uses the F_SCEN wording k % 5, so each of the 5 wordings runs twice.
- 0 fallbacks and 0 early stops in 81 replies.

**Repeat runs added no new data.** The extractor runs at temperature 0.0 (`memory.extract_facts`) and sees only the
child's words. Runs 6–10 stored exactly the same facts as runs 1–5 in every scenario. So each 10-run count is
5 wording results, each counted twice, and one wording that flips moves a count by 2/10. For example, a "≥ 9/10"
criterion means no wording may fail.

| Id | Stage F (5) | Stage G Arm A (10) | Stored strings (Arm A) |
|---|---|---|---|
| F6a any fact | 4/5 | **2/10** | `wishes for mummy for Christmas` ×2 (wording 5, "I want my mummy for Christmas.") |
| F6b any fact | 4/5 | **0/10** | – |
| F7a any fact | 0/5 | 0/10 | – |
| F7b any fact | 0/5 | 0/10 | – |
| F7c any fact (info) | 3/5 | **0/10** | – (fears were not named in the sentence, but none were stored) |
| F1 banana stored | 4/5 | 8/10 | `wants a banana`, `wishes for a banana`, `likes banana`, `wishes for a banana for Christmas` (×2 each) |
| F2 paw patrol stored | 5/5 | 10/10 | `wants Paw Patrol`, `likes paw patrol`, `wishes for Paw Patrol for Christmas`, `likes Paw Patrol`, `wants the paw patrol` (×2 each) |
| F4 bunny stored | 5/5 | **8/10** | `likes a bunny`, `wants a house for their bunny`, `Ziv has a bunny`, `Has a bunny` (×2 each) |
| F4 socks stored | 4/5 | **6/10** | `wants socks for Mommy`, `wants socks for mommy`, `Wants socks for Mommy` (×2 each) |

The same results by wording, Stage F → Stage G Arm A. Only the rows that changed are shown:

| Scenario, wording | Stage F stored | Arm A stored |
|---|---|---|
| F4 w3 "My bunny needs a house. And socks for Mommy." | `Has a bunny`, `Wants socks for Mommy` | **nothing** |
| F4 w4 "Can you bring a house for my bunny and socks for Mommy?" | `has a bunny` | `Ziv has a bunny` (socks missing in both) |
| F6a w1–w3 "I want my mummy/mommy" | `wishes for mummy/mommy` | nothing |
| F6b w1–w4 (dead dog) | `Has a dog` ×3, `Leo wants his dog back` | nothing |
| F7c w1, w2, w4 (dark) | `is scared of the dark` ×2, `Leo doesn't like the dark` | nothing |
| F1 w1 "I want a banana." | `wishes for a banana` | `wants a banana` |
| F2 w1, w5 | `wishes for …` | `wants …` |
| F2 w4 "Santa, Paw Patrol please." | `likes Santa`, `likes Paw Patrol` | `likes Paw Patrol` |

**Part 1 (run once, criterion d).** Remembered facts at the end:
- Emma: `has a cat named Mittens`, `favorite color is purple`
- Leo: `likes dinosaurs`, `wants a red scooter for christmas`
- Ziv: `has a hamster named Nibbles`

Leo's "i'm a little bit scared of the dark" stored nothing (info).

## 3. FOR CLAUDE (chat) TO JUDGE

- **F4 w3.** Arm A stores nothing for "My bunny needs a house. And socks for Mommy." Does the model read "needs a house"
  as something sad? Is one wording dropping two benign facts an acceptable cost for removing the sad facts?
  Pre-registered, it is not.
- **F6a w5.** "I want my mummy for Christmas." still stores `wishes for mummy for Christmas`. Is that a sad fact, or
  an ordinary wish?
- **F7c.** Fear-of-the-dark storage went from 3/5 to 0/10 even though fears were not named. Is that a wanted or an
  unwanted side effect? Don decides whether fears should be stored.
- **Criterion design.** Because extraction is deterministic, the 10-run thresholds test the 5 wordings, not sampling
  noise. Should the next round use more distinct wordings instead of repeat runs?

Santa's spoken replies are in the transcript but were not part of this stage's criteria. Nothing about them is marked
pass.

## 4. Recall check (`out/smoke_live_G-recall-1..5.txt`, `.json`)

`smoke_live.py --tag G-recall-N --only 2`, N = 1..5, run under Arm A:

| Run | Leaks (of 18 replies) | "Remember me" own fact | Strict pet-name recall |
|---|---|---|---|
| 1–5 (each) | 0 | 9/9 | 9/9 |
| **Pooled** | **0 / 90** | 45/45 | **45/45** |

**Denominator.** The prompt says 5 runs pooled, compared against "≥ 49/54". 5 runs give 45 pet-name turns, not 54
(the Stage F baseline 51/54 came from 6 runs). 45/45 (100%) is above 49/54 (90.7%) on either reading.

**This check cannot test extraction.** As noted in Stage F §5, Part 2 preloads the facts, so FACTS_PROMPT reaches it
only through `remember()` after each turn. The check mostly guards against leaks.

## 5. Restore, and what it forced

These steps follow from pre-registered step 4: "if neither arm passes, restore … byte-identical".
- **`santa/persona.py`:** copied back from the snapshot. `diff` and `cmp` show no difference.
- **`tests/spec/test_stage_g.py`:** removed. Two of its tests assert the Arm A sentence, so they would fail on the
  restored prompt and break criterion (f). Its contents are recorded in the `TEST_CHANGES.md` Stage G table. Net test
  change in Stage G: none.
- **Suite after the restore:** **592 passed, 1 skipped**, the same as the baseline.

## 6. Files touched (net, checked with `diff -rq` against the snapshot)

- `tools/probes/smoke_live.py`: new `--tag G` path (`G_DEFAULT_SCEN`, `_g_args`, `main_stage_g`, `g_counts`, `g_line`,
  `g_criteria`). It reuses `F_SCEN`, takes `--scen`, `--runs`, `--name` and `--no-part1`, and runs the Part 1 script
  once. Every other path is unchanged: no flag, `--tag X`, `--tag X --only 2`, `--tag F` and `--rescore`.
- `docs/history/TEST_CHANGES.md`: Stage G section.
- `tools/probes/out/smoke_live_G.txt`, `.json` and `smoke_live_G-recall-1..5.txt`, `.json`: new.
- `docs/history/STAGE_G.md`: this file.

`santa/persona.py` has no net change. These were not touched: `tests/audit`, `santa/legacy/`, `profiles.json`,
`persona_v1.txt`, `SANTA_PROMPT`, the facts note, `spec.py`, `speech.py`, `NAME_RE`. No new `__pycache__`, `.pyc` or
cache directories. `.git/index` is unchanged.

## 7. Not done

- No Arm B (not triggered), and no third wording.
- No fix for the F3 stale wish facts, the F5 replies that lean towards yes, or the deflecting replies to "they yell all
  night".
- No commit.
