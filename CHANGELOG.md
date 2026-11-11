# Changelog

All notable changes to this project. Format follows [Keep a Changelog](https://keepachangelog.com/);
there are no tagged releases yet, so everything is under *Unreleased*, grouped by implementation stage.
Detail for each stage lives in `docs/history/STAGE_*.md`. Design lives in `docs/architecture.md`.

## [Unreleased]

### Memory
- Santa's backstory: fixed home, Mrs. Claus, reindeer and elves in the system prompt (`persona.WORLD_DEFAULT`),
  replaceable with `local/santa_world.txt`.
- Last-call memory: Hang up saves one `Last call: ...` fact per child who spoke at least twice (replaces the previous
  one; same privacy checks as other facts; `SANTA_CALL_SUMMARY=0` turns it off). Code: `Santa.end_call`.
- Santa now sees a child's last 8 saved facts each turn (was 6).

### Home network mode
- Added `python -m santa.web --network`: other devices on the home Wi-Fi can call Santa over HTTPS (mkcert
  certificate in the gitignored `certs/`). The default is unchanged: 127.0.0.1, plain HTTP.
- Other devices must enter a PIN (`SANTA_PIN`, required to start); this Mac never is. 5 wrong tries lock that device
  out for 60 s. The unlock cookie is HttpOnly, SameSite=Strict, and stops working when the server restarts.
- In network mode only one call runs at a time, and `/status` answers only on this Mac.
- The call page uses `wss://` when served over HTTPS.
- Security fix (all modes): the WebSocket now refuses pages from other websites (Origin must match Host). Before,
  any website open in the same browser could connect to `ws://127.0.0.1:8765/ws`, drive a call and read the
  children's names.
- Code: `santa/web/access.py`; tests: `tests/spec/test_network_mode.py`.

### Security fixes (VulnHunter scan 2026-11-10: the High and both Medium findings)
- DNS rebinding (High, WebSocket; Medium, HTTP pages): the server now only answers to its own names, on every request
  and WebSocket: `127.0.0.1`, `localhost`, `::1`, plus this Mac's `.local` name and Wi-Fi address in `--network`
  mode, plus `SANTA_ALLOWED_HOSTS`. Before, a website could point its own name at 127.0.0.1. The browser then sent a
  matching Origin and Host, and this Mac skips the PIN, so the website could run calls and read `/status`, the
  children's names, facts and the photo.
- PIN brute force (Medium): lockouts now escalate per device (1 min, 5 min, then 30 min; they no longer reset to 1
  min). Devices without the PIN are limited to 10 requests per minute in total (`SANTA_GATE_LIMIT`). This caps
  guessing from many addresses. 429 responses carry `Retry-After`.
- uvicorn now runs with `proxy_headers=False`, so an `X-Forwarded-For` header can never change the client address
  that the PIN check uses.
- Tests: `tests/spec/test_network_mode.py`.

### Start/stop scripts hardened (VulnHunter scan of the scripts, 2026-11-10)
- `start-santa.sh` no longer trusts whatever answers on Santa's port (Medium). It confirms that the port is free
  from any account with a direct connection test (`lsof` only sees your own processes). It declares Santa ready
  only when the process listening on the port is the server it just started, or its child. It stops waiting at
  once if that server exits.
- `local/` and `local/run/` are made private (700), and `santa.log` and `server.pid` are created private (600,
  `umask 077`) (Low).
- One settings parser: `santa/local.py` `read_env` handles inline comments (`KEY=10  # note`), quotes, and a `#`
  inside a value (`48#29x`). The start script reads settings through it (`local.shell_exports`, shell-quoted for
  `eval`) instead of its own loop, which cut every value at `#`. Before, uncommenting a template line such as
  `SANTA_GATE_LIMIT=10  # ...` made `run-web.sh` crash at startup.
- Also: `SANTA_PORT` must be a number and `SANTA_BASE_URL` must be http(s). There is no `bash -c` with settings.
  PID files are used only if they point to your own `santa.web` process, so `-1` or a reused PID is never signalled.
  The "older Santa" check matches `-m santa.web` and your uid. The scripts honour `SANTA_LOCAL_DIR`.
  `SANTA_OPEN=0` starts without opening the browser.
- Tests: `tests/spec/test_local_dir.py`, including a round trip of hostile values through `bash eval`.

### "Ho ho ho" once
- Santa now opens the call with one bigger "Ho, ho, ho!". It is voiced on its own, at speed 0.78, followed by a
  0.35 s pause, then the greeting (`santa/web/canned.py`).
- After that he says "Ho ho" only when the child sings or tells a joke (`cues.sings_or_jokes`). The rule is in the
  prompt's later-additions block; `SANTA_PROMPT` and `persona_v1.txt` are unchanged.
- The speech gate removes any other "Ho ho" (`spec.strip_ho`, `brain.ho_once`). `SANTA_HO_ONCE=0` turns it off.
- No "Ho ho" in the fallback line, the song intros or the unknown-song answer.
- The Stage I snapshot tests run with `SANTA_HO_ONCE=0`, like the other later features. Tests that used "Ho ho ho!"
  only as sample text now expect it removed. New tests: `tests/spec/test_ho_once.py`.

### Security alert, 6-digit PIN and the Low findings
- Added a macOS security alert (`santa/web/alerts.py`). It is raised on a PIN lockout, on the rate limit tripping,
  and on an unknown-host request. The dialog offers Stop Santa or Keep Running, defaults to Keep Running, and closes
  itself after 5 minutes. It never stops Santa by itself. At most one alert per 10 minutes. `SANTA_ALERTS=0` turns it
  off.
- `--network` now needs a PIN of at least 6 characters.
- Low findings fixed:
  - POST /unlock stops reading after 1000 bytes (413).
  - Every response forbids framing (`X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`) and sets `nosniff` and
    `no-referrer`.
  - Playback ids are stored only for Santa's own utterances.
  - Binary WebSocket messages over 16 KiB are dropped, and uvicorn `ws_max_size` is 64 KiB.
  - At most 4 call pages can be open (close code 1013). The VAD model loads off the event loop.
  - One call at a time in every mode. Sessions no longer share the brain concurrently.
  - Facts that read like instructions to Santa are never stored (`spec.looks_like_instruction`). This blocks stored
    prompt injection.
  - The gift-promise regexes no longer backtrack catastrophically on runs of `-` or `'`.
- Fixed: Forget last pressed while Santa is answering now skips saving that turn. Before, it deleted the previous
  turn's facts.
- Small fixes:
  - A non-ASCII cookie no longer causes a 500.
  - Bad playback ids are ignored.
  - The hang-up timing list is capped.
- Tests: `tests/spec/test_alerts.py`, `tests/spec/test_low_fixes.py`. `test_add_fact_collapses_whitespace_and_newlines`
  now expects the "New rule" fact to be refused.

### Personal files in `local/`
- Added a gitignored `local/` folder for everything personal: `santa.env` (settings and the network PIN, read by
  `python -m santa.web` and `chat.py`; the shell wins), `santa.jpg` (Santa's picture), `profiles.json`,
  `transcripts/` and `certs/`. `SANTA_LOCAL_DIR` moves it elsewhere. Template: `local.example/`. Code: `santa/local.py`.
- Moved defaults: profiles from `profiles.json` to `local/profiles.json` (an old root file is still used until it is
  moved), the picture from `santa/web/static/santa.jpg` to `local/santa.jpg` (old spot still works), certificates
  from `certs/` to `local/certs/`.
- Added `scripts/run-web.sh` (starts the call page, kept awake with `caffeinate`, flags passed through).
- Tests: `tests/spec/test_local_dir.py`.

### Stage I - conversation arc
- Added `santa/arc.py`: per child, Santa asks once what the child would like for Christmas (by the child's 3rd
  turn), asks two more questions, then says he should get back to the elves and reindeer and asks if the child is
  ready to say goodbye. If the child wants to stay, he offers topics (talk more, the North Pole, the reindeer, the
  elves), and later winds down again. Santa never ends the call himself.
- The arc is a short note on the current user turn only (like the facts note); the system prompt, `SANTA_PROMPT`,
  the facts prompt and every reply rule are unchanged. Guests get no arc. A new Call starts a fresh arc.
- **Off by default** (`SANTA_ARC=1` turns it on): neither the shipped wording (Arm A) nor the pre-registered
  fallback (Arm B) passed every live check, so, as pre-registered, the code is kept and the default is off.
  Details: `docs/history/STAGE_I.md`.
- Persona item F12a (a new question after "I don't want you to go") is intended behaviour when the arc is on.

### Stage H - voice web app
- Added `santa/web/`: FastAPI call page on 127.0.0.1 with Call / Hang up buttons, a still Santa picture and an
  adult strip (child buttons, Guest, Forget last).
- Added voice pipeline: AudioWorklet capture, Silero VAD, mlx-whisper small.en, Kokoro v1.0, call state machine.
- Only the speech gate can reach TTS; no audio or transcripts are written to disk.
- Phase 3 changed from a USB handset to this web page.
- 30-minute soak passed (121 turns, 0 errors, no memory growth, model stayed loaded). It found Hang up being held up
  after Forget last by the busy brain thread; fixed in `santa/web/session.py` (not re-soaked yet).
- Not yet measured: speech recognition on real children's voices; echo with real speakers.

### Stage G
- Tested an extractor change; restored the original facts prompt (the change hid sad facts but dropped a benign
  wording).
- Sad facts can still be stored, so Stage H adds an adult "Forget last" control.

### Stages A-F
- TODO: summarize from `docs/history/STAGE_A.md` through `STAGE_F.md` (single rules file `santa/spec.py`, remove-only
  streaming speech filter, memory off the critical path, model choice `ai/gemma4:e4b`).

### Known open items
- Persona issues F5, F7a; stale wish facts F3; F9 wording. (F12a is intended behaviour when the Stage I arc is on.)
- Low, accepted trade-off of fix P1-1 (keep negation inside stand-alone `*...*` and `(...)` spans): a stand-alone
  stage direction that contains a negation word (for example "no" or "not") is now spoken, because the negation stays
  with its span instead of being cut out of it. Rare, since stage directions are normally stripped. Revisit if one is
  ever heard.
