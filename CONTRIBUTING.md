# Contributing

Thanks for your interest in Talking Santa! Bug reports, ideas and pull requests are all welcome.

## Ways to help

- **Found a bug?** Open an [issue](../../issues). Say what you did, what you expected and what happened. Include
  your macOS version, browser, and the model you used (`SANTA_MODEL`).
- **Have an idea or a question?** Open an issue whose title starts with "Idea:" or "Question:".
- **Found a security problem?** Do **not** open a public issue. Report it privately, as described in
  [SECURITY.md](SECURITY.md).
- **Want to fix something?** Open a pull request. For larger changes, open an issue first so we can agree on the
  approach before you spend time on it.

Never include real children's names, recordings, transcripts or a `profiles.json` in an issue or pull request. Use
made-up names such as Emma, Leo and Ziv, as the tests do.

## Development setup

Requires macOS (Apple silicon for the voice app), Python 3.12+, and Docker Desktop with Model Runner.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # add ",web" to run the voice app; see README for the model downloads
bash scripts/install-git-hooks.sh  # gitleaks pre-commit hook: blocks commits that contain secrets
mkdir -p local                     # your personal files (gitignored); template in local.example/
```

## Before you open a pull request

- [ ] `pytest` passes. It takes about 25 s and needs no model server: the tests use fakes.
- [ ] New behaviour has a test. Every bug fix gets a test that would have caught it.
- [ ] Nothing personal is committed. `local/`, `profiles.json`, certificates and audio are gitignored; keep it that
      way.
- [ ] If you touched the server, sessions or memory, `bash scripts/security-scan.sh` shows no new findings.
- [ ] User-facing changes are noted in [CHANGELOG.md](CHANGELOG.md) under *Unreleased*.

## Ground rules for this project

These come from the design (see [docs/architecture.md](docs/architecture.md)). Pull requests that break them will
not be merged:

- **Nothing leaves the Mac at runtime.**
  - No cloud APIs, analytics or telemetry.
  - Network access is allowed only for one-time model downloads during setup.
- **Child safety comes first.** Everything Santa says goes through the safety gate in `santa/spec.py`.
  - The gate only removes text; it never rewrites it.
  - New rules belong in `spec.py`, with tests.
- **Safe defaults.**
  - The server listens on `127.0.0.1` unless the user passes `--network`.
  - New features that accept outside input need the same Host, PIN and limit checks as the existing routes
    (`santa/web/access.py`).
- **Personal data stays in `local/`.** Code refers to personal files only by name, through `santa/local.py`.

## Style

- Python: follow the surrounding code, with short functions and comments that say *why*.
- Keep pull requests focused: one fix or feature each.
- Write commit messages in the imperative ("Add PIN lockout"), with a body that explains the reason when it isn't
  obvious.

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
