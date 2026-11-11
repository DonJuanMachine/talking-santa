# Talking Santa

Local, private talking Santa for small kids. LLM served by Docker Model Runner; nothing leaves the Mac.

```
mic -> VAD -> STT -> [ Santa brain: persona + memory + safety ] -> TTS -> speaker
```

Status: Phase 1 (typed chat) and Phase 2 (voice call page, `santa/web/`) are built. Design: `docs/architecture.md`.
History: `CHANGELOG.md`. Per-stage reports: `docs/history/`.

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # or: pip install -e ".[dev]" to also get the test tools
mkdir -p local && cp profiles.example.json local/profiles.json   # then edit it (local/ is gitignored, see below)
# Docker Desktop > Settings > Model Runner > enable host-side TCP (port 12434)
docker model pull ai/gemma4:e4b       # the chosen model (only ONE large model loaded at a time)
python scripts/check_model.py          # Phase 0: connectivity + latency
python chat.py                         # Phase 1: type as the kids ("Emma: hi santa")
python evals/bench.py gen ai/gemma4:e4b   # benchmark -> evals/results/; then: python evals/bench.py report (see docs/model-selection.md)
```
Output filter rollback: `SANTA_FILTER=legacy python chat.py` uses the old repair filter (`santa/legacy/`).
Edit `local/profiles.json` with your kids' names/ages and facts (it is never committed; see "The children" under Customize). Tune Santa in `santa/persona.py`.
Override model with `SANTA_MODEL=ai/gemma4:e4b (default)`.

## Easy start and stop
```bash
scripts/start-santa.sh              # this Mac only
scripts/start-santa.sh --network    # home Wi-Fi too
scripts/stop-santa.sh               # stops Santa, frees the model's memory
```
`start-santa.sh` checks Docker, Model Runner, the model, memory, the voice (and, with `--network`, the PIN and
certificates). For anything that is off it asks "y/N" and fixes it, then starts Santa in the background and opens
the page. The log is `local/run/santa.log`. `stop-santa.sh` stops what the start script started.

## Phase 2: Santa on a web page (voice in, voice out)
A FaceTime-style page on this Mac: big green **Call**, big red **Hang up**, a still Santa picture, and a small
grown-ups strip (one button per registered child, **Guest**, **Forget last**). Everything runs locally; the server
listens on 127.0.0.1 only, unless you start it with `--network` (see **Use on your home network** below). Design:
`docs/architecture.md`.

One-time install (needs the network once; the venv lives outside the repo):
```bash
python3.12 -m venv ~/.venvs/talking-santa-h
~/.venvs/talking-santa-h/bin/pip install -e ".[web,dev]"   # fastapi, uvicorn, onnxruntime, mlx-whisper, kokoro-onnx, ...
M=~/.cache/talking-santa/models; mkdir -p $M
curl -L -o $M/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o $M/voices-v1.0.bin  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
curl -L -o $M/silero_vad.onnx  https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
~/.venvs/talking-santa-h/bin/python -c "from huggingface_hub import snapshot_download as s; s('mlx-community/whisper-small.en-mlx')"
```
Run (Docker Model Runner up with `ai/gemma4:e4b`, as in Phase 1):
```bash
scripts/run-web.sh
# open http://127.0.0.1:8765 in Chrome or Safari, allow the microphone, press Call
```
`scripts/run-web.sh` is `python -m santa.web` with offline model loading, kept awake with `caffeinate`; it passes any
flags through. `SANTA_PYTHON` picks another interpreter.
- Voice: Kokoro `am_michael` at 0.9 by default (`SANTA_VOICE`, `SANTA_SPEED`). A Kokoro blend is written as weighted
  names, e.g. `SANTA_VOICE=am_santa:70,bm_fable:30`. To try Kyutai Pocket TTS instead, add
  `SANTA_TTS=pocket` (default voice `peter_yearsley`; any built-in Pocket voice via `SANTA_VOICE`; no speed setting;
  needs `HF_HUB_OFFLINE=1`, and the files fetched once by `tools/probes/j1_audition.py pocket-fetch`).
- Children are read from `local/profiles.json` (register them once with `/add Name` in `chat.py`).
- Every Call starts as **Guest**. Santa switches to a child when the child says their registered name, or when a
  grown-up presses that child's button. **Forget last** removes the facts Santa saved from the selected child's most
  recent turn; a second press does nothing.
- No audio and no transcripts are written anywhere. `--debug-audio` (off by default) saves each child utterance
  to `santa/web/debug_audio/` (gitignored); delete it after debugging.
- Tuning: `SANTA_EOS_MS` (end-of-speech wait, default 1200), `SANTA_EOS_EXTEND=0` (turn off the one-time
  extension to 1800 ms for short turns), `SANTA_VOICE` / `SANTA_SPEED` (default `am_michael` / 0.9; audition WAVs
  in `tools/probes/out/voice_audition/`), `SANTA_STT_MODEL` (default `mlx-community/whisper-small.en-mlx`).
- The **Timings** button shows per-turn latency (numbers only). `--verbose` logs the same numbers to the console.
- Conversation arc (asks each child's Christmas wish, then offers to say goodbye or to tell about the North Pole): off by default (`SANTA_ARC=0`); `SANTA_ARC=1` turns it on (experimental, see `docs/history/STAGE_I.md`).
- Gift question (on by default): if gifts have not come up by a child's 5th turn, Santa gently asks one Christmas-wish
  question; never while the child sounds sad (and for 2 turns after). `SANTA_GIFT_ASK=0` turns it off,
  `SANTA_GIFT_ASK_TURN` changes the turn. Off when `SANTA_ARC=1` (the arc has its own ask). Code: `santa/gifts.py`.
- Santa's backstory: he has a fixed North Pole world (Mrs. Claus is Mary, the nine reindeer, four named elves) so he
  answers the same way every call. Replace it with your own in `local/santa_world.txt` (see `local.example/README.md`);
  the built-in text is `WORLD_DEFAULT` in `santa/persona.py`.
- Last-call memory (on by default): when a call ends with Hang up, Santa saves one short line per child who spoke at
  least twice, such as `Last call: told Santa about a new puppy and asked for a train`, so the next call can pick up
  where this one left off. It is built from the child's own words, passes the same privacy checks as other saved facts,
  and each new one replaces the old one. No transcript is stored. It is not made if the connection simply drops.
  `SANTA_CALL_SUMMARY=0` turns it off; delete the line from `local/profiles.json` to forget it. Code: `Santa.end_call`.
- Time of day (on by default): on the call's first turn and on goodbyes, Santa is told this Mac's time, so he says good
  morning, not good night, at 9 AM. `SANTA_TIME_NOTE=0` turns it off.
- "Ho ho ho" once (on by default): Santa laughs one big, slower "Ho, ho, ho!" when he answers the call. After that
  he says "Ho ho" only when the child sings or tells a joke. The prompt asks for this and the speech gate removes any
  other "Ho ho". `SANTA_HO_ONCE=0` turns it off. To change the laugh, edit `laugh`, `LAUGH_SPEED` and `LAUGH_PAUSE_S`
  in `santa/web/canned.py`.
- Gentle mode (on by default): when a child sounds sad or scared, Santa comforts softly, then stays calm for that
  child's next 3 turns (no "Ho ho ho", no jokes). `SANTA_GENTLE=0` turns it off.
- Songs (on by default): Santa never offers to sing. When a child asks for a song, Santa says the first verse of
  Jingle Bells or Deck the Halls (the one asked for, else taking turns) from fixed text, with no model call. The voice
  speaks the words; it cannot sing a tune. Asked for another song ("sing Frosty"), Santa says he doesn't know that
  one and offers one he knows; a yes on the child's next turn gets it. `SANTA_SONGS=0` turns it off. Code:
  `santa/songs.py`.
- To use your own picture or change Santa's name, see **Customize** below.
- To call from a phone, iPad or another computer, see **Use on your home network** below.

### Use on your home network
`--network` lets other devices on your Wi-Fi call Santa. Browsers only allow the microphone over HTTPS, so this
needs a certificate your devices trust, made once with [mkcert](https://github.com/FiloSottile/mkcert) (free, runs
on this Mac, no account).

One-time setup on this Mac:
```bash
brew install mkcert            # add `brew install nss` if anyone uses Firefox
mkcert -install                # creates your private certificate authority (asks for your password once)
mkdir -p local/certs           # gitignored
mkcert -cert-file local/certs/santa.pem -key-file local/certs/santa-key.pem \
  "$(scutil --get LocalHostName).local" "$(ipconfig getifaddr en0)" localhost 127.0.0.1
```
On each phone or tablet, once: copy `rootCA.pem` from `mkcert -CAROOT` to the device (AirDrop works for iPhone and
iPad), install the profile, then on iOS turn it on in Settings > General > About > Certificate Trust Settings.
Never copy `rootCA-key.pem` anywhere.

Pick a PIN (at least 6 characters) and put it in `local/santa.env` (gitignored): `SANTA_PIN=<your PIN>`. Then:
```bash
scripts/run-web.sh --network
# open https://<your Mac's name>.local:8765 on the other device (the startup message prints the address)
```
The first time, macOS asks whether Python may accept incoming connections: choose Allow.

What changes in this mode:
- Other devices see a PIN screen first. This Mac is never asked. After 5 wrong PINs, that device is locked out for
  1 minute, then 5 minutes, then 30 minutes for each further 5 wrong tries. Restarting the server asks every device
  for the PIN again.
- Devices that have not entered the PIN get at most 10 requests per minute, all devices together
  (`SANTA_GATE_LIMIT`). Unlocking takes about 2, so a family member is never slowed down; a PIN guesser using many
  addresses is.
- One call at a time (in every mode): a second page that presses Call hears nothing and sees "Santa is on another
  call". At most 4 Santa pages can be open at once.
- Security alert (macOS, on by default; `SANTA_ALERTS=0` turns it off): a PIN lockout, the rate limit tripping, or a
  request for an unknown name pops up a dialog on this Mac with **Stop Santa** / **Keep Running**. It defaults to
  Keep Running and closes by itself after 5 minutes; Santa is never stopped automatically, so bad requests alone
  cannot end a child's call. At most one alert per 10 minutes. Nothing is sent off the Mac.
- `/status` (it lists the children's names) answers only on this Mac.
- If the Mac's Wi-Fi address changes, use the `.local` name, or re-run the `mkcert` line above.

In every mode the server only answers to its own names: `127.0.0.1` and `localhost`, plus, with `--network`, this
Mac's `.local` name and Wi-Fi address (read at startup). A request for any other name gets "unknown host". This stops
DNS rebinding, where a website you visit points its own name at your Mac to reach Santa. To use another name (say
a router DNS entry), add it to `local/santa.env`: `SANTA_ALLOWED_HOSTS=santa.home`.

**Gotcha:** loading two big models at once causes `Compute error` (Metal out of memory). Run `docker model unload --all` before switching models.

## Customize
Everything here is optional. After any edit, reload the page; restart `python -m santa.web` for Python changes.

**Your personal files go in `local/`.** Git ignores that folder, so your settings, PIN, picture, children's profiles
and certificates are never committed; the code only knows the file names. Template and details:
`local.example/README.md`. Settings go in `local/santa.env`, one `KEY=VALUE` per line (every option is listed in
`local.example/santa.env.example`); a value set in your shell wins.

**Santa's picture.** The call screen shows a drawn Santa (`santa/web/static/santa.svg`). To use your own picture, save
it as `local/santa.jpg` (or `.png` / `.webp`; square works best, for example 800x800) and reload the page. Delete it
to go back to the drawing, or edit the SVG to change the drawing.

**Santa's name.** The name appears in two places, and you will usually want to change both:
- *On screen*, in `santa/web/static/index.html`: the big name on the call screen (`<div id="name">Santa Claus</div>`),
  the browser-tab `<title>`, the `Call Santa` button labels and the picture's `alt` text. In `santa/web/static/app.js`:
  the status line `SUB` (`Call Santa`), `LABEL` (`Santa is listening`, `Santa is thinking...`) and the `Call Santa` button label.
- *What Santa says*, in `santa/persona.py`: the first line of the system prompt (`You are Santa Claus, ...`) and the
  `I'm Santa ...` example. The fixed spoken lines are in `santa/web/canned.py` (the greeting and "didn't quite hear that")
  and `FALLBACK` in `santa/spec.py`. Changed canned lines are re-recorded in Santa's voice automatically the next time
  the server starts.

  The reply rules are tuned around Santa, so after renaming him run `pytest` and make a test call.

**Santa's personality.** Edit the prompt in `santa/persona.py`. Compare changes with `python evals/bench.py gen <model>` then `python evals/bench.py report` (see `evals/`).

**Santa's voice.** `SANTA_VOICE`, `SANTA_SPEED` and `SANTA_TTS` (see the Phase 2 section above). A Kokoro blend is written
as weighted names, for example `SANTA_VOICE=am_santa:70,bm_fable:30`.

**The children.** Copy `profiles.example.json` to `local/profiles.json` and put your kids' names and ages in it (or
register them with `/add Name` in `chat.py`). An older `profiles.json` in the repo root still works until you move it.

*Making Santa more personal.* Santa reads only two fields per child, `age` and `facts` (a list of short sentences).
Put what makes each child special in `facts`: what they like, the town they live in, their grandparents' names (as the
child says them), pets, favorite things. Other keys are kept in the file but Santa ignores them.
```json
{
  "children": {
    "Emma": {
      "age": 4,
      "facts": [
        "lives in Maplewood",
        "calls her grandparents Nana and Pop",
        "has a cat named Biscuit",
        "loves snow angels and drawing",
        "wants a drawing pad"
      ]
    }
  }
}
```
- Edit the file with Santa stopped (Santa saves to it during calls and would overwrite your edit). Check it with
  `python3 -m json.tool local/profiles.json`. A broken file falls back to `profiles.json.bak`, the last good save.
- Only the **last 8 facts** go into each turn, and Santa keeps at most **20** per child (oldest dropped first, including
  yours). Put the most important facts last, and check the file after a few calls.
- Facts you type by hand are not run through the safety filters that Santa's own saved facts get. Keep it to a town or
  state, never a street address, phone number or last name.
- Santa only mentions a child's facts when talking to that child.

**The model.** `SANTA_MODEL` (default `ai/gemma4:e4b`); `SANTA_BASE_URL` points at a different OpenAI-compatible server.

## Layout
- `santa/` - the core: `brain.py` (history + memory + reply, reused by the voice phase), `persona.py` (system prompt),
  `spec.py` (every reply rule), `speech.py` (remove-only streaming filter), `safety.py` (wrapper for old callers),
  `memory.py` (per-child facts in `local/profiles.json`), `local.py` (finds your files in `local/`), plus `arc.py`,
  `cues.py`, `gifts.py`, `songs.py`
  - `santa/web/` - Phase 2 call page: VAD + end of speech, Whisper STT, Kokoro TTS, call state machine (uses the brain unchanged)
  - `santa/legacy/` - frozen copy of the old output filter (`SANTA_FILTER=legacy` rollback)
- `chat.py` - Phase 1 typed chat
- `tests/` - pytest suites (`spec/`, `review/`); run with `pytest` (no model server needed: the client is faked)
- `evals/` - toddler scenario benchmark (`bench.py`, `cases.json`, `personas/`, `results/`)
- `tools/` - not run by pytest: `probes/` (per-stage probes, benchmarks and live smoke tests that need the model and/or
  voice stack running; outputs go to the gitignored `tools/probes/out/`), `review/` and `audit/` (evidence scripts and
  experiments behind the reviews)
- `scripts/` - `check_model.py` (smoke test), `install-git-hooks.sh` + `git-hooks/` (gitleaks pre-commit), `security-scan.sh`
- `docs/` - `architecture.md`, `model-selection.md` (why Gemma 4 e4b: benchmark method, data, results); `docs/history/` - per-stage reports, audit and review write-ups. `CHANGELOG.md` - history by stage. `SECURITY.md` - security policy and model. `CONTRIBUTING.md` - how to report bugs and contribute
- `notes/` - local-only scratch notes and Claude Code prompts. **Gitignored: never commit it.**

## Tests
```bash
pip install -e ".[dev]"      # or use the voice venv from above
pytest                        # ~920 tests, ~25 s, no model server needed
```
Tests always use a fresh temporary `SANTA_LOCAL_DIR` and `SANTA_PROFILES`, whatever your shell exports.

### Regenerate requirements.lock
`requirements.lock` is a `pip freeze` of the environment that actually runs Santa (web and voice stack included).
Regenerate it from that environment after any install or upgrade, then audit it:
```bash
<runtime-venv>/bin/python -m pip freeze | grep -v -e "@ file://" -e "^-e" > requirements.lock
pip-audit -r requirements.lock --no-deps --disable-pip
```
It is a record for auditing, not an install recipe: some pins (torch, mlx) are platform-specific (Apple silicon).

## Security & privacy
Built for small children, so privacy and safety come first:
- **Private by default.** Speech recognition, the language model and the voice all run on this Mac. There is no
  telemetry, and no audio or transcripts are saved.
- **Local only unless you choose otherwise.** The server listens on `127.0.0.1`. `--network` adds HTTPS, a PIN,
  escalating lockouts, a rate limit and a macOS alert with a Stop Santa button.
- **Protected against common web attacks:** DNS rebinding, cross-site WebSocket hijacking, clickjacking, PIN brute
  force, prompt injection through stored memories, and request-flooding denial of service. Each protection has
  regression tests.
- **Safe speech.** Every sentence Santa says passes a safety gate: no gift promises, no private details.
- **Checked regularly.** A gitleaks pre-commit hook runs on every commit. `scripts/security-scan.sh` runs gitleaks,
  pip-audit (on `requirements.txt` and on `requirements.lock`, the versions that actually run), Snyk, bandit, Semgrep and Trivy. The dependency scan only covers published Python package advisories; see SECURITY.md for what it cannot see. An AI-assisted review (VulnHunter, 2026-11-10) found issues, and all
  were fixed.

Found a security problem? Please report it privately; see [SECURITY.md](SECURITY.md). For bugs and ideas, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Prior art (none is local + multi-child)
- unconv/santa-gpt - web app, OpenAI STT/LLM/TTS
- jordicor/santa-claus-is-calling - Santa phone calls via cloud APIs; prompt-injection ideas worth reading
- ArvinZhuang/local-her - local speech-to-speech tuned for Apple Silicon (Phase 2 reference)
- shivu0070/local-voice-ai - Whisper + Ollama + Piper pipeline
