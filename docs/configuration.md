# Configuration

Every setting Santa reads, with its default. The defaults below are the values in `santa/config.py`,
`santa/web/settings.py` and the module that reads each variable.

- Put values in `local/santa.env` (one `KEY=VALUE` per line; the template is `local.example/santa.env.example`) or export
  them in your shell. **A value exported in your shell wins** over the file.
- **Restart Santa after changing anything.** Settings are read once, when Santa starts.
- `1` and `0` turn a feature on and off. For the feature switches in the conversation table, `0` turns the feature off;
  `SANTA_ALERTS` and `SANTA_EOS_EXTEND` also accept `false`, `no`, `off` or an empty value for off.
- `scripts/run-web.sh` sets `HF_HUB_OFFLINE=1` itself, so a value in `local/santa.env` cannot turn it off for a start
  through `run-web.sh` or `start-santa.sh`; it only takes effect for a direct `python -m santa.web` start (see
  [Files and folders](#files-and-folders)).
- Never write a PIN into a document or an issue; `<your PIN>` stands for it below.

## Model and server

| Setting | Default | What it does |
|---|---|---|
| `SANTA_MODEL` | `ai/gemma4:e4b` | The language model's name on the model server. |
| `SANTA_BASE_URL` | `http://localhost:12434/engines/v1` | The OpenAI-compatible model server. The children's words go to whatever server you name. |
| `SANTA_TIMEOUT` | `15.0` | Seconds before a normal model request gives up (Santa then says the fallback line). |
| `SANTA_WARMUP_TIMEOUT` | `90.0` | Seconds a warm-up request may take (loading the model takes 6 to 30 s). |
| `SANTA_WARMUP_RETRY` | the warm-up timeout (90) | After a failed warm-up, a reply does not warm up again for this many seconds. |
| `SANTA_IDLE_REWARM` | `300` | If the last good model answer is older than this many seconds, warm up first. |
| `SANTA_TEMP` | `0.7` | Sampling temperature for replies. |
| `SANTA_MAX_TOKENS` | `120` | Longest reply the model may produce, in tokens. |
| `SANTA_FILTER` | `prefix` | The output filter. `legacy` switches to the alternative filter in `santa/legacy/`, which repairs a reply instead of only removing text. |
| `SANTA_PORT` | `8765` | The call page's port. `--port` overrides it. `scripts/start-santa.sh` requires a number from 1 to 65535. |
| `SANTA_PYTHON` | `~/.venvs/talking-santa-h/bin/python` | Scripts only: the Python interpreter that `run-web.sh` and `start-santa.sh` use. |
| `SANTA_OPEN` | `1` | `scripts/start-santa.sh` only: `0` starts Santa without opening the browser. |

## Voice

| Setting | Default | What it does |
|---|---|---|
| `SANTA_TTS` | `kokoro` | The voice engine: `kokoro` or `pocket` (Kyutai Pocket TTS, which needs the extra install in the README's [Pocket TTS](../README.md#pocket-tts-optional) section). Anything else stops Santa at start. |
| `SANTA_VOICE` | `am_michael` (`peter_yearsley` when `SANTA_TTS=pocket`) | The voice name. A Kokoro blend is written as weighted names, for example `am_santa:70,bm_fable:30`. |
| `SANTA_SPEED` | `0.9` | Speaking speed. Kokoro only; Pocket TTS has no speed setting. |
| `SANTA_MODELS_DIR` | `~/.cache/talking-santa/models` | Where the Kokoro model and voices and the Silero VAD file are read from. |

## Listening and speech recognition

| Setting | Default | What it does |
|---|---|---|
| `SANTA_EOS_MS` | `1200` | Milliseconds of silence that end the child's turn. |
| `SANTA_EOS_EXTEND` | `1` (on) | Wait once longer after a short turn. `0` turns the extension off. |
| `SANTA_EOS_EXTEND_MS` | `1800` | The longer wait, in milliseconds. |
| `SANTA_EOS_SHORT_MS` | `1500` | A turn with less speech than this many milliseconds gets the longer wait once. |
| `SANTA_MIN_SPEECH_MS` | `250` | Shorter clips are dropped and never transcribed. |
| `SANTA_MAX_UTTERANCE_S` | `20` | A turn longer than this many seconds is ended at once. |
| `SANTA_STT_MODEL` | `mlx-community/whisper-small.en-mlx` | The speech-recognition model (a Hugging Face repository name). |
| `SANTA_STT_MIN_LOGPROB` | `-1.0` | A transcript with lower confidence than this becomes "say that again". |
| `SANTA_STT_MAX_NO_SPEECH` | `0.8` | A transcript whose no-speech probability is higher than this becomes "say that again". |

## Conversation features

| Setting | Default | What it does |
|---|---|---|
| `SANTA_ARC` | `0` (off) | `1` turns on the conversation arc (Christmas wish, then offer to say goodbye). Experimental. |
| `SANTA_GIFT_ASK` | `1` (on) | The gift question. Off when `SANTA_ARC` is on. |
| `SANTA_GIFT_ASK_TURN` | `5` | The child's turn number that first gets the gift question. |
| `SANTA_GENTLE` | `1` (on) | Gentle mode after a sad or scared turn. |
| `SANTA_SONGS` | `1` (on) | Santa says a carol's first verse when asked, from fixed text. |
| `SANTA_HO_ONCE` | `1` (on) | "Ho ho ho" once when answering, then only for a child's song or joke. |
| `SANTA_TIME_NOTE` | `1` (on) | Tell Santa this Mac's time on the first turn and on goodbyes. |
| `SANTA_CALL_SUMMARY` | `1` (on) | Save one `Last call:` line per child at Hang up. |

## Timing and failure

| Setting | Default | What it does |
|---|---|---|
| `SANTA_SLOW_S` | `10` | Seconds with no first sentence before Santa says the hold line and the page shows "taking a while". `0` turns it off. |
| `SANTA_HOLD_EVERY_S` | `60` | The hold line plays at most once per this many seconds in one call. |
| `SANTA_TICK_S` | `2.5` | Seconds between the server's liveness ticks during a call. `0` turns them off. The page treats 6 seconds without any message as a lost connection. |
| `SANTA_SILENCE_S` | `45` | Seconds of silence before "I'm still here"; after the same time again Santa says goodbye and hangs up. |
| `SANTA_KEEPALIVE_S` | `100` | Between calls, warm up the model if it has not answered for this many seconds. `0` turns it off. |

The model timeouts (`SANTA_TIMEOUT`, `SANTA_WARMUP_TIMEOUT`, `SANTA_WARMUP_RETRY`, `SANTA_IDLE_REWARM`) are in
[Model and server](#model-and-server). The behavior is described in the README's
[Failure behavior](../README.md#failure-behavior).

## Network mode and security

| Setting | Default | What it does |
|---|---|---|
| `SANTA_PIN` | none | The PIN other devices must enter with `--network`: at least 6 characters, for example `SANTA_PIN=<your PIN>`. This Mac never has to enter it. |
| `SANTA_GATE_LIMIT` | `10` | PIN tries per minute from devices that have not entered the PIN, all together (at most 5 from any one device). |
| `SANTA_ALLOWED_HOSTS` | none | Extra names the server answers to, comma-separated (for example a router DNS name). |
| `SANTA_ALERTS` | `1` (on) | The macOS security alert with a Stop Santa button. `0` turns it off. |

## Files and folders

| Setting | Default | What it does |
|---|---|---|
| `SANTA_LOCAL_DIR` | `local/` in the repository | Where your personal files live. Set it in the shell only; it cannot be set in `local/santa.env`. |
| `SANTA_PROFILES` | `local/profiles.json` | The children's profiles file. A `profiles.json` in the repository folder is used until you move it, if the new one does not exist. |
| `HF_HUB_OFFLINE` | `1` | Keeps the speech-model loader from contacting Hugging Face. The entry point sets it unless your shell or `local/santa.env` already does; `scripts/run-web.sh` sets it itself. Pocket TTS refuses to start unless it is `1`. |
| `HF_HUB_DISABLE_TELEMETRY` | `1` | Turns off Hugging Face telemetry. Set by the entry point on the same terms. |
| `PYTHONDONTWRITEBYTECODE` | `1` in `run-web.sh` | Set by `scripts/run-web.sh` so Python writes no bytecode files. |

## Command-line flags

`python -m santa.web` (and `scripts/run-web.sh`, which passes its flags through):

| Flag | Default | What it does |
|---|---|---|
| `--port` | `SANTA_PORT` (8765) | The port to listen on. |
| `--network` | off | Let other devices call, over HTTPS and behind the PIN. Needs `SANTA_PIN` and the certificate files. |
| `--cert` | `local/certs/santa.pem` | The HTTPS certificate for `--network`. |
| `--key` | `local/certs/santa-key.pem` | The HTTPS private key for `--network`. |
| `--debug-audio` | off | Save each child utterance to `santa/web/debug_audio/` (gitignored). The children's voices; delete them after debugging. |
| `--metrics-file` | none | Append one line of numbers per turn to this file. No text. |
| `--verbose` | off | Log per-turn timings to the console. |

Scripts: `scripts/start-santa.sh --network` starts with the home-network checks; `scripts/security-scan.sh
--with-snyk-code` also runs Snyk Code, which uploads source.

## Values that are not settings

These are fixed in the code; changing them means editing it.

| Value | Where |
|---|---|
| Wrong PINs before a lockout 5; lockouts 60 s, 300 s, then 1800 s | `santa/web/settings.py` |
| Open call pages at most 4; unlock form at most 1000 bytes; audio message at most 16 KiB; WebSocket message at most 64 KiB | `santa/web/server.py`, `santa/web/session.py`, `santa/web/__main__.py` |
| Security alert: one per 600 s, closes after 300 s | `santa/web/alerts.py` |
| Ring lasts 2 to 8 s; microphone closed 300 ms after Santa speaks; playback grace 3 s | `santa/web/settings.py` |
| Voice activity thresholds 0.5 (start) and 0.35 (keep); 300 ms before and 200 ms after speech kept | `santa/web/settings.py` |
| Recognition rejects repeated text above a compression ratio of 2.4 | `santa/web/settings.py` |
| History window 12 messages, trimmed 8 at a time | `santa/config.py` |
| Facts: 8 sent per turn, 20 kept, 100 characters each, 2 extracted per turn; a `Last call:` line needs 2 turns | `santa/persona.py`, `santa/memory.py`, `santa/brain.py` |
| Reply length: 45 words, 3 sentences after an optional opening laugh | `santa/spec.py` |
