## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Tests

- [ ] I ran `pytest` and it passes (about a minute, no model server needed).
- [ ] New behavior has a test, and every bug fix has a test that would have caught it.

## Checklist

- [ ] No private files, recordings or real names in the diff (nothing from `local/`, no `profiles.json`, no transcripts, no certificates). Examples use made-up names.
- [ ] Docs are updated if behavior changed (README, `docs/configuration.md`, `docs/architecture.md`), and user-facing changes are noted in `CHANGELOG.md` under *Unreleased*.
- [ ] Safety rules stay in `santa/spec.py`, and the filter only removes text.
- [ ] Nothing new leaves the Mac at runtime, and anything that accepts outside input has the same Host, PIN and limit checks as the existing routes.
