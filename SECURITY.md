# Security

Talking Santa is a voice app for small children. It runs on one Mac, and nothing it hears or says leaves that
machine. This page explains how to report a problem, what the app protects against, and how it is checked.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.** Report it privately instead: on this repository's
**Security** tab, choose **Report a vulnerability** (GitHub private vulnerability reporting). Only the maintainer can
see the report, and you can discuss a fix there before anything is made public.

A useful report says:
- what an attacker could do, and from where (same Mac, home Wi-Fi, or any website)
- the steps to reproduce it, or a proof of concept
- the version or commit you tested

You can expect an acknowledgement within a week. This is a personal project, so there is no bug bounty.

For bugs that are not security problems, open a normal issue (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Supported versions

There are no releases yet. Fixes go to the `main` branch only.

## Security model

**What it protects:**
- the children's names, ages and remembered facts
- Santa's picture
- the ability to start a call and talk to a child

**Who it trusts:**
- Anyone using this Mac (loopback) is trusted: it is the family's own computer.
- By default the server listens on `127.0.0.1` only.
- With `--network`, other devices on the home Wi-Fi can connect. They need HTTPS and a PIN.

**What it assumes:** an adult is in the room during calls, and the home network is not hostile, though it may hold
untrusted devices.

**Out of scope:**
- someone who already controls this Mac
- exposing the server to the internet (do not forward its port)
- the safety of the local language model itself, beyond the output filter described below

## Protections against common attacks

| Attack | Protection | Tests / code |
|---|---|---|
| A website you visit reaches the local server (DNS rebinding, cross-site WebSocket hijacking) | The server answers only to its own names (Host allowlist on every request). WebSocket Origin must match. | `tests/spec/test_network_mode.py` |
| Guessing the PIN | Lockouts get longer each time (1 min, 5 min, 30 min). All devices without the PIN share a limit of 10 requests a minute. The PIN must be 6+ characters and is compared in constant time. The unlock cookie is random, HttpOnly and SameSite=Strict. | `tests/spec/test_network_mode.py` |
| Someone actively probing the server | A macOS alert on lockouts, rate limiting or unknown hosts. It offers to stop the server and never stops it by itself. | `tests/spec/test_alerts.py` |
| Clickjacking | `frame-ancestors 'none'` and `X-Frame-Options: DENY` on every response, plus `nosniff` and `no-referrer` | `tests/spec/test_low_fixes.py` |
| Prompt injection through stored memories | Remembered facts that read like instructions to Santa are never saved. Facts are single-line and length-limited. | `tests/spec/test_low_fixes.py` |
| Unsafe things said to a child | Every spoken sentence passes a remove-only safety gate (no gift promises, no private details, no "I'm an AI"). The voice refuses unchecked text. | `tests/spec/` |
| Denial of service | Request body, audio frame and open-connection caps; one call at a time; safety regexes free of catastrophic backtracking | `tests/spec/test_low_fixes.py` |
| Path traversal | Static files are confined to their folder | `santa/web/server.py` |
| Spoofed client address | Proxy headers are ignored (`X-Forwarded-For` cannot fake "this Mac") | `santa/web/__main__.py` |
| Secrets or family data in git | Personal files live in the gitignored `local/` folder. A gitleaks pre-commit hook blocks secrets. | `scripts/git-hooks/pre-commit` |

**Privacy by design:**
- The language model, speech recognition and voice all run locally.
- There is no telemetry.
- No audio or transcripts are saved unless you turn on a debug flag.
- Logs hold timings and event reasons, never what was said.

## How security is checked

- **Every commit:** a gitleaks pre-commit hook. Install it with `bash scripts/install-git-hooks.sh`.
- **On demand:** `bash scripts/security-scan.sh` runs the tools below. Reports are written outside the repo.

  | Check | Tools |
  |---|---|
  | Secrets, in the working tree and git history | gitleaks |
  | Dependency CVEs | pip-audit (`requirements.txt` and `requirements.lock`), Snyk (`requirements.txt`) |
  | Static analysis | bandit, Semgrep |
  | Broad sweep | Trivy |
  | Snyk Code (opt-in, uploads source) | `--with-snyk-code` |

  `requirements.txt` pins almost nothing, so the exact versions that run are recorded in `requirements.lock`
  (a `pip freeze` of the runtime environment). The scan audits that file as pinned and fails if pip-audit reports
  anything. It checks Python package versions against public advisory databases only. It cannot see native code
  bundled inside wheels (for example torch and mlx), model files, or advisories that are not published yet. The lock
  is a snapshot: regenerate it after any install or upgrade (command in the README) and run the scan again.

- **Regression tests:** each protection above has tests, which run with the normal suite (`pytest`).
- **Reviews:** an AI-assisted security review ([VulnHunter](https://github.com/capitalone/VulnHunter)) was run on
  2026-11-10. All confirmed findings were fixed, with regression tests; see the Security entries in
  [CHANGELOG.md](CHANGELOG.md).

Scans and reviews reduce risk; they do not prove the absence of vulnerabilities. Reports are welcome.
