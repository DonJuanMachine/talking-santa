# Stage A report: measurements before building (2026-11-05)

Live model: `ai/gemma4:e4b` only, one model loaded, `docker model unload --all` before and after each run. Model time:
A1 13.4 min, A2 9.8 min. No product code was edited. New files are only in `tools/probes/` (2 scripts, `out/`, this report).
Rollback tarball: `.snapshots/pre-impl-20261105-1836.tar.gz`. Test baseline (temp venv): 294 passed, 3 failed (the known stale
round-2 tests), 1 xfailed. `tests/audit/` is byte-identical before and after (sha check). No new `__pycache__`. No git command changed state.

Details: `out/latency.md` (A1, with verdict), `out/shape.md` (A2, every changed reply + 20 random replies per persona),
raw data in `out/latency.jsonl`, `out/shape-v1.jsonl`, `out/shape-v3.jsonl`.

---

## 1. Latency verdict (A1)

**Supported: cause (i), the prompt changing between turns. Refuted as the main cause: (ii), the extraction call evicting the cache.
Confidence: high.** The server returns its own cache counters (`timings.cache_n` = prompt tokens reused, `prompt_n` = processed
fresh), so this is measured, not inferred.

- On this machine prompt processing is slow: **≈4 ms per uncached token** (210–250 tokens/s). A cold 845-token prompt costs
  3.4 s to first token. The identical request a second later costs 0.05 s. TTFT ≈ uncached tokens × 4 ms.
- **Today (V0)** reprocesses ~720 tokens every turn from turn 3 on. The system prompt changed between consecutive turns 7 of 9
  times (new facts, and a different active child's facts each turn).
- **Extraction does not evict the Santa prefix.** Its call shares only BOS, but the next Santa turn still reuses the cache. With
  the stable prompt, extraction adds ~55 fresh tokens (+0.25 s) to the next turn (V4 vs V3), not a full reprocess.
- **Moving extraction after reply() alone does nothing for TTFT** (V2 2.85 s vs V0 2.80 s). It only removes ~0.6 s from the reply()
  wall time.
- **New cause, not in the audit: the sliding 12-message window.** From turn 6 on, every turn drops one old message, so all
  history (~230 tokens) is reprocessed: ≈1.2–1.4 s even with no facts. Block trimming halves this (blocks of 4 = a miss every 2nd turn).

Long_session_memory, turns 1–9, 5 reps (n=45 per variant):

| variant | TTFT p50 | TTFT p95 | vs V0 (p50) | stream total p50 / p95 | fresh tokens p50 |
|---|---|---|---|---|---|
| V0 today (extraction inside reply) | 2.80 | 3.32 | — | 3.55 / 4.07 (reply() wall 4.21 / 4.68) | 716 |
| V1 extraction off | 0.35 | 1.51 | −87% | 1.46 / 2.42 | 26 |
| V2 extraction after reply | 2.85 | 3.41 | +2% | 3.62 / 4.45 | 714 |
| V3 stable prompt, no extraction | 0.27 | 1.26 | −90% | 1.26 / 2.18 | 18 |
| **V4 stable prompt + extraction after turn** | **0.52** | **1.32** | **−81%** | 1.36 / 2.22 | 73 |
| V5 (extra diagnostic) facts pre-seeded, no extraction, today's prompt | 1.53 | 3.46 | −45% | 2.32 / 4.08 | 234 |

V4 is the design you would ship (memory still works). Recall in V4 is intact: Pickles 5/5, Theo 5/5. A simple name check found
0 cross-child mentions in 50 turns. V4's p95 (1.32 s) comes entirely from the two block-trim turns (6 and 8).

## 2. Shape table (A2)

20 single-turn cases + 4 multi-turn scenarios, N=3, extraction off: 132 replies per persona, 0 model errors.
"Remove-only" is the audit prototype (`prefix_filter_prototype.speak`). It allows two questions and caps at opener + 3 sentences / 45 words.

| metric | persona v1 | persona v3 (runs today) |
|---|---|---|
| **raw shape-compliant** (≤1 "?", ≤ opener+3 sentences, ≤45 words, no stage dir, no markup, no safety hit) | **131/132 (99.2%)** | 106/132 (80.3%) |
| raw breaks: more than 3 sentences | 0/132 | **24/132 (18.2%)**, all exactly 4 |
| raw breaks: 2 questions / stage dir / markup / safety / >45 words | 1 / 0 / 0 / 0 / 0 | 1 / 1 / 1 / 0 / 0 |
| **passes the remove-only filter unchanged** | **132/132 (100%)** | 107/132 (81.1%) |
| material intervention: today's filter / remove-only | 1/132 (0.8%) / 0/132 | 22/132 (16.7%) / 21/132 (15.9%) |
| today's filter: answer lost / question demoted | 0 / 1 | **5** / 1 |
| remove-only: final question cut by the sentence cap | 0 | **20/132** |
| fallback (either filter) | 0 | 0 |
| raw two-question rate | 1/132 (0.8%) | 1/132 (0.8%) |
| no-question rate: raw / heard remove-only / heard today | 26.5% / 26.5% / 26.5% | 12.1% / 27.3% / 12.1% |
| mean words raw / mean sentences raw | 18.0 / 2.92 | 22.7 / 3.39 |
| latency single-turn: TTFT p50/p95, total p50/p95 (s) | 0.19 / 2.07, 1.00 / 2.83 | 0.32 / 3.69, 1.61 / 4.88 |
| latency multi-turn: TTFT p50/p95, total p50/p95 (s) | 1.48 / 2.89, 2.06 / 3.52 | 1.53 / 4.05, 2.31 / 4.89 |

(A2 latency is in today's code with extraction off. Single-turn TTFT depends on what the server has cached, so compare the
total times more than the TTFTs. v3's prompt is ~120 tokens longer and its replies ~5 words longer.)

**What I saw reading the 20 random replies per persona** (verbatim in `out/shape.md`):
- **v1**: short (2–3 sentences), warm, answers the child. Weak spots: some generic follow-ups ("Are you having fun today?"), little
  North Pole magic, one clumsy line ("Is Theo two years old, that's a big boy!"), and "I am a real person!" to "are you a robot?".
  Grief and fear replies are exactly the persona's script (goldfish: "Oh, Ziv, I am so sorry to hear that. That sounds really sad.
  Let's tell your mommy or daddy together.").
- **v3**: more vivid and magical, but a fixed 4-beat template: echo exclamation, "Ho ho, …" line, magic line, question. That is
  where the 4-sentence replies come from; the persona's own echo example is two sentences. **The magic bullet also fires in sad
  turns.** The goldfish reply ends "Do you like the twinkly lights in the toy workshop?". Today's filter then keeps only
  "Ho ho, Ziv. Do you like the twinkly lights in the toy workshop?": **the audit's goldfish failure, reproduced on e4b with the
  persona the app runs today.** Other patterns: "Jingle jingle." tacked onto grief or fear replies; "Hi Leo! A dinosaur!" (echoing a profile fact
  when the child only said hi); after an address (redacted for the model): "My elves are working on some twinkly lights near your home."

## 3. Recommendation: persona v1 (confidence: medium-high)

Strongest evidence: v1 is 99.2% raw shape-compliant vs 80.3% for v3, and passes the remove-only filter unchanged 132/132 vs 107/132.
v3's extra sentence is the magic line, and in sad turns that line turns a caring reply into a cheerful topic change.
v1 is also ~0.6 s faster per single-turn reply (shorter replies).
Limits: one model, one run, n=132 per persona, one non-blind reader (me), no TTS. v1's cost is less magic and more generic
questions, which a parent should judge by reading `out/shape.md`.

## 4. Filter work Stage B needs

- **With v1: minimal.** 132/132 (100% ≥ 95%) pass the remove-only filter unchanged. Stage B keeps the filter to safety + markup +
  the hard cap at a sentence boundary.
- **If you keep v3:** 81.1% < 95%. What fails is almost entirely the 3-sentence cap: 24/132 replies have exactly 4 short sentences
  (all ≤ 45 words), and a prefix cap cuts the final question in 20 of them. Options: (a) raise `MAX_CONTENT_SENTENCES` to 4 (a
  shape rule, so it's your call; 0 v3 replies exceeded 4), or (b) accept the lost question. Rewriting is out of scope either way.
- One filter bug both filters share, to fix in B1: `*jingle jingle*` inside a sentence is deleted as a "stage direction"
  ("The reindeer just gave a little *jingle jingle* sound." → "…gave a little sound."). Sound words in emphasis should be kept.

## 5. Latency change Stage B should build (B3)

The ≥30% threshold is clearly met (V4 −81%, V3 −90%). Build both:
- **(a) `Santa.remember()` after the reply** (one model call in reply()). It doesn't help TTFT on its own (V2), but it removes
  ~0.6 s from reply() wall time and is needed for streaming anyway.
- **(b) A constant system prompt per session** (all names and ages, no facts). The active child's facts go in a short note on the current user
  turn only (never stored in history), with block-wise history trimming. This is what moves TTFT (V3/V4).

Two refinements the data supports. Each needs your OK, because they go slightly beyond the literal plan:
- **Bigger trim blocks.** With blocks of 4 messages, every other turn after turn 6 costs ~1.2 s (V4 p95 1.32 s). Trimming 8
  messages at a time (keep ≥ 4) would make that one turn in four. Less history is fine because facts come from memory now.
- **Warm-up with the session's real system prompt** (instead of "hi"), so the first turn hits the cache. The identical-request
  test shows 3.4 s → 0.05 s for a cached prefix. Not measured end to end.

## 6. Surprises and contradictions with the audit

1. The audit's inferred cause is right for the system prompt but incomplete: **the sliding window is a second, independent cause**
   (~1.2 s per turn after turn 6). Its alternative cause (extraction eviction) is **wrong**: the server keeps several cached prompts.
2. **Prompt processing is ~4 ms/token**, slower than I'd expect on an M5. Every uncached token matters: the first turn of any session
   pays ~3 s unless warm-up primes the real prompt.
3. Persona v3, unmeasured until now, is **worse than v1** on shape. With today's filter it reproduces the goldfish failure on e4b
   (the audit had only shown it on Ministral).
4. The remove-only prototype's low lost-answer rate (0.5%) was measured on v1/v2 data. On v3 its cost is a different one: the cut final question (20/132).
5. Importing `prefix_filter_prototype.py` re-runs the audit and **rewrites files in `tools/audit/experiments/out/`**. My probe
   points that output at a temp dir. Stage B must not import it as-is from tests (copy the logic into `santa/speech.py`).
6. Latency target: V4 TTFT p95 1.32 s, plus about 0.3 s to the first full sentence. That gives first-sentence p95 ≈ 1.6 s before
   STT/TTS, so ≤ 1.5 s p95 first audio **probably needs the bigger trim blocks and/or the warm-up priming**. With Whisper and TTS
   sharing the GPU: unknown.

## 7. Decisions I need from you (my recommended defaults)

| # | Decision | Recommended default |
|---|---|---|
| 1 | Persona | **v1** (copy `evals/personas/persona_v1.txt` into `SANTA_PROMPT` exactly) |
| 2 | Two short questions allowed? | **Yes** (0.8% of replies under either persona) |
| 3 | No question at all allowed? | **Yes** (v1: 26.5% of replies; delete the 30% target test) |
| 4 | Model | **ai/gemma4:e4b** |
| 5 | Fallback line | **Keep the current one**; no regeneration (0 fallbacks in 264 new replies) |
| 6 | Keep "naughty list" blocked? | **Yes** (0/264 replies said it; both personas say "nice list") |
| 7 | Latency target | **First audio ≤ 1.5 s p95** in a memory-enabled session |
| 8 | (new) B3 refinements | **Yes to both**: trim 8 messages at a time; warm-up with the real system prompt |
| 9 | (new, only if v3) | Raise the sentence cap to opener + 4, or accept lost questions |
