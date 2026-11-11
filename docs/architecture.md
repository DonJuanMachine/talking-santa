# Talking Santa: architecture

> **Status: outline.** Sections marked TODO are to be written. Facts already stated here come from the README,
> module docstrings and `docs/history/STAGE_*.md`. Keep this file about the *current* design; history goes in
> `CHANGELOG.md`, private notes go in `notes/` (gitignored). Do not put children's names or any profile data here.

## 1. Purpose and constraints

- A private, local, talking Santa for small children (ages 4-5), always used with an adult in the room.
- Hard constraints: nothing leaves the Mac at runtime; no Chinese-developed models; child safety before everything
  else; Santa must not feel slow.
- Non-goals: TODO (cloud use, accounts, multi-household, barge-in). Home-network use is opt-in (`--network`).

## 2. System overview

```
browser mic -> AudioWorklet (16 kHz) -> WebSocket -> VAD + end-of-speech -> STT
     -> Santa brain (persona + memory + reply rules) -> speech gate -> TTS -> WebSocket -> browser speaker
```

- Processes and ports: browser page; `santa.web` server (FastAPI/uvicorn, 127.0.0.1:8765); Docker Model Runner
  serving the LLM on localhost:12434. TODO: diagram.
- Only one large model is loaded at a time (the LLM). STT, TTS and VAD are small and run in the server process.

## 3. Components

### 3.1 Santa brain (`santa/`)
| File | Role |
|---|---|
| `brain.py` | history + memory + reply; `reply_stream`, `reply_ex`, `remember`, `warm_up` |
| `persona.py` | system prompt (edit here to tune Santa); facts note and conversation-arc note wordings |
| `arc.py` | conversation arc: per-child stage machine that picks a short note for the current turn (pure logic) |
| `spec.py` | the one place where reply rules live: pure functions, no I/O |
| `speech.py` | remove-only, prefix-only streaming filter, sentence by sentence |
| `safety.py` | thin wrapper over `spec.py` and `speech.py` for older callers |
| `memory.py` | per-child facts in `local/profiles.json` (text only) |
| `config.py` | central config, overridable by environment variables |

TODO: prompt layout and why it is cache-friendly; how `remember()` runs after the reply is spoken.

#### Conversation arc
When switched on (`SANTA_ARC=1`), Santa steers each child's conversation: chat, ask once what the child would like for Christmas, ask a couple more
questions, then offer to say goodbye. If the child wants to stay, he offers topics (talk more, the North Pole, the
reindeer, the elves) and later winds down again. He never ends the call: the grown-up does (Hang up).

```
 turn 1-2        turn 3 (+ up to 2 retries)       2 question replies (max 4 turns)    1 turn       3 turns
  CHAT ─────────────► ASK note ──"?"+"Christmas"──► FOLLOW ─────────────────────────► WIND ──────► OFFER ──┐
                                                                                        ▲                  │
                                                                                        └──────────────────┘
```

- `santa/arc.py` keeps the state per registered child, per conversation: turns, stage, whether the Christmas
  question was asked, follow-up count, turns in the current stage. A new conversation (every Call) starts fresh,
  because the web app makes a new `Santa` per Call.
- Each turn gets at most one short note (wordings in `persona.py`), added to the **current user turn only**, after
  the facts note. It is never stored in history and never in the system prompt, so the prompt cache still works.
- The state moves on only when something was actually spoken (never on the fallback line), using the spoken text:
  "asked" means the reply has a "?" and the word "Christmas"; a follow-up is a reply with a "?".
- Every note ends with the same two safety clauses: if the child says goodbye, say a warm goodbye and ask nothing;
  if the child sounded sad or scared, comfort them and ask nothing this turn.
- Guests and unregistered speakers get no arc and no note. The arc follows whichever child is active.
- **Off by default.** Neither note wording passed every Stage I live check (`docs/history/STAGE_I.md`), so
  `SANTA_ARC` defaults to 0 (no note, no state: requests are byte-identical to the pre-arc code). `SANTA_ARC=1`
  turns it on.

### 3.2 Reply rules and safety model
- SAFETY rules are enforced: a sentence that trips one is never spoken, and nothing after it is.
- SHAPE rules are measured, not enforced by rewriting; the only one that acts is the hard length cap, and it stops at
  a sentence boundary.
- Filtering is remove-only: nothing is added, reordered or reworded.
- Only the speech gate reaches TTS (`santa/web/safe.py`); canned lines are checked against the same rules at import.
- TODO: list of SAFETY rule categories (not the blocklist itself), fallback line behavior, legacy filter
  (`santa/legacy/`, `SANTA_FILTER=legacy`).

### 3.3 Memory
- TODO: what is stored (facts per child), extraction prompt, when it runs, isolation between children, what the
  prompt receives for the active child.
- TODO: "Forget last" behavior and the `.bak` file; known limitation that sad facts can still be stored.

### 3.4 Voice web app (`santa/web/`)
| File | Role |
|---|---|
| `settings.py` | every tunable, overridable by environment variable |
| `audio.py`, `vad.py`, `endpoint.py` | frames, Silero VAD, end-of-speech logic |
| `stt.py` | mlx-whisper; "say that again" rules from confidence |
| `safe.py` | the only door to TTS |
| `tts.py`, `canned.py` | Kokoro; cached canned lines |
| `brain_adapter.py` | wraps the brain; one brain thread; cancellable stream |
| `session.py` | call state machine, mic gating, per-turn metrics |
| `server.py`, `__main__.py` | FastAPI app, `/ws` protocol, `/status`, keep-alive loop |
| `static/` | page, playback queue, adult strip, Timings overlay |

TODO: WebSocket message protocol (client and server messages).

## 4. Call lifecycle
- States: IDLE, RINGING, GREETING, LISTENING, THINKING, SPEAKING, HANGUP. TODO: transition diagram.
- Every Call resets the active child to Guest and starts a fresh conversation.
- Hang up stops all audio at once and cancels the model stream, then plays a short goodbye before returning to IDLE.
- The microphone is ignored while Santa speaks and for a short guard time after.
- TODO: silence handling (still-here line, goodbye), keep-alive pings between calls.

## 5. Who is speaking
- TODO: how the active child is chosen (name heard once, adult buttons, Guest), and the known weakness of
  switching on any spoken name. See "Open decisions".

## 6. Data and privacy
- Stored: per-child text facts in `local/profiles.json` (gitignored). Not stored: audio, transcripts, logs with content.
- Logs and `/status` hold numbers and reason codes only. `--debug-audio` is off by default.
- Network: 127.0.0.1 by default. `--network` binds 0.0.0.0 over HTTPS (mkcert) behind a PIN for non-loopback
  clients, one call at a time, and `/status` stays loopback-only (`santa/web/access.py`). In every mode the WebSocket
  rejects a browser Origin that is not this server. Model downloads are one-time.
- Personal files (settings + PIN, picture, profiles, transcripts, certificates) live in the gitignored `local/`
  (`santa/local.py`). TODO: anything else a developer must never commit.

## 7. Latency budget
- Targets: median processing (end of speech to first audio) under 2.0 s; median total (last voiced frame to first
  audio) under 3.5 s.
- TODO: table of per-stage medians, and which part is the deliberate end-of-speech wait. Source: Stage H report.

## 8. Models and provenance
| Role | Model | Developer | License |
|---|---|---|---|
| LLM | Gemma 4 e4b via Docker Model Runner | Google DeepMind | TODO |
| STT | Whisper small.en via mlx-whisper | OpenAI / Apple | MIT |
| TTS | Kokoro-82M v1.0 via kokoro-onnx | hexgrad (handle) | Apache-2.0 |
| VAD | Silero VAD v5 | Silero team | MIT |

Why Gemma 4 e4b, how candidate models were benchmarked, the test data and results: `docs/model-selection.md`.

TODO: country/provenance column and the project's decision on the no-Chinese-models rule.

## 9. Configuration
- TODO: table of environment variables (`SANTA_MODEL`, `SANTA_FILTER`, `SANTA_EOS_MS`, `SANTA_EOS_EXTEND`,
  `SANTA_VOICE`, `SANTA_SPEED`, `SANTA_STT_MODEL`) with defaults and effects.

## 10. Testing and evaluation
- `tests/spec`, `tests/review`: automated suites (`pytest`). `evals/`: toddler scenario benchmark.
  `tools/`: probes, live smoke tests and audit experiments (not run by pytest); `docs/history/`: per-stage reports.
- TODO: how to run each, what "recall" and "leak" mean in the smoke tests, why live tests need the model running.

## 11. Operations
- One large model at a time; run `docker model unload --all` before switching models.
- TODO: startup checklist, offline checklist, what to check before show day (echo test, real-child rehearsal,
  profile review).

## 12. Known limitations and open decisions
- STT accuracy on child speech is not measured.
- Speaker selection by spoken name can attribute one child's words to another.
- TODO: smart-turn end-of-speech detection, barge-in. Network mode trusts the client IP for the "this Mac" PIN
  exemption, so do not put a reverse proxy in front of it.

## 13. Design decisions
- **LLM: Gemma 4 e4b** over Gemma 4 12B and 26B-A4B and Ministral 3 8B and 14B. It was the fastest to first
  token and followed the reply rules best; the larger models only won small amounts of judged warmth and magic.
  Evidence: `docs/model-selection.md`, `docs/history/STAGE_A.md`.

TODO: short entries for the rest (decision, alternatives, reason, evidence file). Known so far: Whisper over Gemma audio input for STT; mlx-whisper over whisper.cpp; Kokoro over Piper; web page instead of
a USB handset.
