# Security

Talking Santa is a voice app for young children. It runs on one Mac, and Santa's own code makes no network calls except
to the model server on that same Mac. This page explains how to report a problem, what the app protects against, and
how it is checked.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.** Report it privately instead: on this repository's
**Security** tab, choose **Report a vulnerability** (GitHub private vulnerability reporting). Only the maintainer can
see the report, and you can discuss a fix there before anything is made public.

A useful report says:
- what an attacker could do, and from where (same Mac, home Wi-Fi, or any website)
- the steps to reproduce it, or a proof of concept
- the version or commit you tested

This is a personal project: reports are handled on a best-effort basis, and there is no bug bounty.

For bugs that are not security problems, open a normal issue (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Supported versions

The project has no tagged releases. Fixes go to the `main` branch only.

## Security model

**What it protects:**
- the children's names, ages and remembered facts
- the ability to start a call and talk to a child

**Who it trusts:**
- Anyone using this Mac (loopback) is trusted: it is the family's own computer.
- By default the server listens on `127.0.0.1` only.
- With `--network`, other devices can connect from any network this Mac is on (Wi-Fi, Ethernet, VPN). They need HTTPS
  and a PIN. Do not use it on untrusted networks.

**What it assumes:** an adult stays in the room for every call, and the home network is not hostile, though it may hold
untrusted devices.

**Out of scope:**
- someone who already controls this Mac
- exposing the server to the internet (do not forward its port)
- the safety of the local language model itself, beyond the output filter described below

## Protections against common attacks

| Attack | Protection | Tests / code |
|---|---|---|
| A website you visit reaches the local server (DNS rebinding, cross-site WebSocket hijacking) | The server answers only to its own names (Host allowlist on every request). A browser's WebSocket Origin must match; a client that sends no Origin (not a browser) still needs to be on this Mac or know the PIN. | `tests/spec/test_network_mode.py` |
| Guessing the PIN | Lockouts get longer each time (1 min, 5 min, 30 min). PIN tries from devices without the PIN share a limit of 10 a minute, at most 5 from any one address, so a single ordinary device cannot lock the others out; someone using several addresses can still block PIN entry for a while. The PIN page itself is never limited. A PIN try sent by another website is refused before it is counted. The PIN must be 6+ characters and is compared in constant time. The unlock cookie is random, HttpOnly and SameSite=Strict. | `tests/spec/test_network_mode.py`, `tests/spec/test_pin_rate_limit.py`, `tests/spec/test_unlock_origin.py` |
| Someone actively probing the server | A macOS alert on lockouts, rate limiting or unknown hosts. It offers to stop the server and never stops it by itself. | `tests/spec/test_alerts.py` |
| Clickjacking | `frame-ancestors 'none'` and `X-Frame-Options: DENY` on every response, plus `nosniff` and `Referrer-Policy: same-origin` (no referrer to other sites; `no-referrer` would make browsers send the PIN form with `Origin: null`, which the PIN page's own check refuses) | `tests/spec/test_low_fixes.py`, `tests/spec/test_unlock_origin.py` |
| Prompt injection through stored memories | Remembered facts that read like instructions to Santa are blocked by a keyword check and never saved, and so are facts that claim what Santa promised, said or gave. Facts are single-line, limited to 100 characters, and have brackets removed so they cannot close the facts note. Facts typed by hand are not checked. | `tests/spec/test_low_fixes.py`, `tests/spec/test_round1_facts.py` |
| Unsafe things said to a child | The first line of defence is the persona prompt, which tells Santa never to promise a specific gift and never to discuss being an AI. Then every spoken sentence is checked by a word-pattern filter that removes known shapes (gift promises, repeating addresses or phone numbers, scary words, Santa claiming to be an AI). The filter only removes text; its one addition is a fixed fallback line when nothing safe is left. The voice refuses text that has not been checked. The filter is not exhaustive: it misses wording outside its patterns, and the known gaps are listed in CHANGELOG.md ("Known open items") and pinned in `tests/spec/test_accepted_gate_gaps.py`. | `tests/spec/` |
| Denial of service | Request body, audio frame and open-connection caps; one call at a time. Malformed requests (a bad Origin, a file name with a NUL byte or too long for the disk, deeply nested JSON) are refused without an error. The safety patterns have timing tests for the shapes known to be slow. | `tests/spec/test_low_fixes.py`, `tests/spec/test_regex_timing.py`, `tests/spec/test_malformed_requests.py` |
| Path traversal | Static files are confined to their folder | `santa/web/server.py` |
| Spoofed client address | Proxy headers are ignored (`X-Forwarded-For` cannot fake "this Mac") | `santa/web/__main__.py`, `tests/spec/test_startup_guards.py` |
| Secrets or family data in git | Personal files live in the gitignored `local/` folder. A pre-commit hook blocks private files and secrets; install it with `scripts/install-git-hooks.sh`. `git commit --no-verify` skips it. | `scripts/git-hooks/pre-commit` |

Most of these protections have regression tests; the 6-character PIN rule and ignoring proxy headers are tested in
`tests/spec/test_startup_guards.py`. Path confinement does not have a test of its own.

**About the AI wording.** The first line of defence is the persona prompt: Santa is told to stay in character and not
discuss being an AI or a computer with the children. The filter is a pattern filter: it removes sentences in known
shapes where he says he is an AI, robot, computer, chatbot, language model or a named AI product. It lets him say he is
not a computer. It is not exhaustive: for example, "I am... an AI." (three dots in the middle) is spoken (CHANGELOG.md,
"Known open items"). That is why an adult stays in the room for every call.

**Privacy by design:**
- The language model, speech recognition and voice run on this Mac. Santa's own code makes no network calls except to
  the model server on the same Mac (`localhost:12434` by default). The entry point keeps the speech-model loader
  offline unless you set `HF_HUB_OFFLINE` yourself. Setup downloads need the internet once. If you point
  `SANTA_BASE_URL` at another computer, the children's words go there. With Pocket TTS, use a built-in voice name: a
  web address in `SANTA_VOICE` may be downloaded. Docker Desktop is separate software with its own
  settings.
- Santa's code sends no telemetry.
- The children's profiles, their backups, chat transcripts and debug recordings that Santa writes are readable only by
  your macOS account (files 0600, folders 0700), however Santa is started (`tests/spec/test_private_files.py`). A file
  you copy or edit yourself, such as `local/profiles.json` or `local/santa.env`, keeps the permissions it was made with
  (usually readable by other accounts) until Santa next saves it, so the install makes the folder private with
  `chmod 700 local`; `scripts/start-santa.sh` sets it again at every start.
- The call page saves no audio or transcripts. `--debug-audio` saves recordings, and the typed chat (`chat.py`) saves
  transcripts to `local/transcripts/`; `/forget` in `chat.py` deletes them. The README lists everything that is
  written to disk.
- Logs hold timings and reasons, not speech. The model server (Docker) keeps its own logs.

## How security is checked

- **Every commit:** a pre-commit hook that blocks private files and secrets (gitleaks). Install it with
  `bash scripts/install-git-hooks.sh`. It can be skipped with `git commit --no-verify`.
- **On demand:** `bash scripts/security-scan.sh` runs the tools below. Reports are written outside the repo. A tool that
  is not installed is skipped, and only a pip-audit failure makes the run fail.

  | Check | Tools |
  |---|---|
  | Secrets, in the working tree and git history | gitleaks |
  | Dependency CVEs | pip-audit (`requirements.txt` and `requirements.lock`), Snyk (`requirements.txt`) |
  | Static analysis | bandit (medium severity and up), Semgrep |
  | Broad sweep | Trivy |
  | Snyk Code (opt-in, uploads source) | `--with-snyk-code` |

  `requirements.txt` pins almost nothing, so the exact versions that run are recorded in `requirements.lock`
  (a `pip freeze` of the runtime environment). The scan audits that file as pinned and fails if pip-audit reports
  anything. It checks Python package versions against public advisory databases only. It cannot see native code
  bundled inside wheels (for example torch and mlx), model files, or advisories that are not published yet. The lock
  is a snapshot: regenerate it after any install or upgrade (command in the README) and run the scan again.

- **Regression tests:** most protections above have tests, which run with the normal suite (`pytest`).
- **Reviews:** AI-assisted reviews ([VulnHunter](https://github.com/capitalone/VulnHunter)) on 2026-11-10 and
  2026-11-19. The 2026-11-19 review of the web server and scripts found 1 Medium and 16 Low issues, plus 4 it could
  not prove. The Medium, 6 of the Lows and 1 of the unproven ones are fixed; the [CHANGELOG](CHANGELOG.md) lists each
  fix, and the rest, with the reason each is accepted, under "Known open items".

Scans and reviews reduce risk; they do not prove the absence of vulnerabilities. Reports are welcome.
