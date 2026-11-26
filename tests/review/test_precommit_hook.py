"""The pre-commit hook blocks private paths and personal data (P10-4).

Every test builds a throw-away git repo with its own HOME and an empty global git config, copies the hook in, and
points SANTA_PII_TERMS / SANTA_PII_TERMS_CS at synthetic term files holding made-up values. The real term files in
the owner's home folder are never opened: HOME is a temp dir in every subprocess. Set SANTA_TEST_HOOK to run the same
cases against another copy of the hook (for example the installed .git/hooks/pre-commit).
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = Path(os.environ.get("SANTA_TEST_HOOK") or ROOT / "scripts" / "git-hooks" / "pre-commit")

NAME_CI = "zorbleflax"      # synthetic: matched case-insensitively
NAME_CS = "Quillbert"       # synthetic: matched case-sensitively (its lowercase form is an ordinary word)


class Repo:
    def __init__(self, base: Path):
        self.dir = base / "repo"
        self.home = base / "home"
        self.home.mkdir()
        self.dir.mkdir()
        (base / "gitconfig").write_text("")
        self.ci = base / "terms-ci.txt"
        self.cs = base / "terms-cs.txt"
        self.ci.write_text(NAME_CI + "\n")
        self.cs.write_text(NAME_CS + "\n")
        bindir = base / "bin"
        bindir.mkdir()
        if not any(Path(d, "gitleaks").exists() for d in ("/opt/homebrew/bin", "/usr/local/bin")) \
                and not shutil.which("gitleaks"):
            stub = bindir / "gitleaks"
            stub.write_text("#!/bin/sh\nexit 0\n")
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.path = f"{bindir}:{os.environ.get('PATH', '/usr/bin:/bin')}"
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.hooksPath", ".git/hooks")

    def env(self, **extra):
        env = {
            "PATH": self.path,
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": str(self.home.parent / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "SANTA_PII_TERMS": str(self.ci),
            "SANTA_PII_TERMS_CS": str(self.cs),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        env.update(extra)
        return env

    def git(self, *args, check=True, **extra):
        r = subprocess.run(["git", *args], cwd=self.dir, env=self.env(**extra), capture_output=True, text=True)
        if check and r.returncode != 0:
            raise AssertionError(f"git {args} failed: {r.stderr[-400:]}")
        return r

    def write(self, rel, text="x\n", binary=False):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            p.write_bytes(text)
        else:
            p.write_text(text)

    def install_hook(self):
        dst = self.dir / ".git" / "hooks" / "pre-commit"
        shutil.copy(HOOK, dst)
        dst.chmod(0o755)

    def commit_unhooked(self, msg="seed"):
        self.git("commit", "-q", "--no-verify", "-m", msg)

    def commit(self, *paths, force=False, **extra):
        """Stage paths (git add -f when force) and commit with the hook installed. Returns (rc, output)."""
        self.git("add", *(["-f"] if force else []), "--", *paths)
        r = self.git("commit", "-q", "-m", "t", check=False, **extra)
        return r.returncode, r.stdout + r.stderr


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path)
    r.write("README.md", "seed\n")
    r.git("add", "README.md")
    r.commit_unhooked()
    r.install_hook()
    return r


# ------------------------------------------------------------------------------------- (a) private paths
BLOCKED = [
    ("profiles.json", "profiles.json*"),
    ("santa/web/profiles.json", "profiles.json*"),
    ("santa/profiles.json.bak", "profiles.json*"),
    ("calls.json", "calls.json*"),                  # the call log: children's names and call times
    ("fam2/calls.json", "calls.json*"),             # next to a SANTA_PROFILES file outside local/
    ("fam2/calls.json.corrupt.2", "calls.json*"),
    ("fam2/calls.json.tmp", "calls.json*"),
    ("local/settings.txt", "local/"),
    ("deep/er/local/a.txt", "local/"),
    ("transcripts/a.txt", "transcripts/"),
    ("santa/transcripts/a.txt", "transcripts/"),
    (".env", ".env*"),
    (".env.local", ".env*"),
    ("sub/.env.prod", ".env*"),
    ("santa.env", "santa.env"),
    ("cfg/santa.env", "santa.env"),
    ("santa/web/debug_audio/a.txt", "debug_audio/"),
    (".snapshots/a.txt", ".snapshots/"),
    ("notes/x.md", "notes/"),
    ("docs/notes/x.md", "notes/"),
    ("santa/web/.cache/a.txt", "santa/web/.cache/"),
    ("evals/backup/a.json", "evals/backup/"),
    ("tools/probes/out/a.txt", "tools/**/out/"),
    ("tools/a/b/out/c.txt", "tools/**/out/"),
    ("tools/out/c.txt", "tools/**/out/"),
    ("x_VULNHUNT_RESULTS_1/README.md", "*_VULNHUNT_RESULTS_*/"),
    ("a.pem", "*.pem"),
    ("certs/server.key", "*.key"),
    ("a/b/c.p12", "*.p12"),
    ("rec/x.m4a", "*.m4a"),
    ("a/b/X.WAV", "*.wav"),
    ("clip.mp3", "*.mp3"),
    ("run.log", "*.log"),
    ("a/x.sqlite", "*.sqlite"),
    ("d/e/x.DB", "*.db"),
    ("certs/a.txt", "certs/"),
    ("a/b/Certs/c.txt", "certs/"),
]

ALLOWED = [
    "local.example/santa.env.example",
    ".env.example",
    "sub/.env.example",
    "santa.env.example",
    "santa/ok.py",
    "docs/notes.md",
    "tools/probes/outline.md",
    "santa/web/cache/x.py",
    "docs/dialog.md",
    "santa/db.py",
    "docs/log.md",
    "certsx/a.txt",
    "docs/certs.md",
]


@pytest.mark.parametrize("path,rule", BLOCKED)
def test_private_path_is_blocked_even_with_force_add(repo, path, rule):
    repo.write(path, "harmless\n")
    rc, out = repo.commit(path, force=True)
    assert rc != 0, out
    assert path in out and f"rule: {rule}" in out, out
    assert repo.git("rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_root_and_nested_profiles_json_are_blocked_after_forced_add(repo):
    for path in ("profiles.json", "santa/web/profiles.json"):
        repo.write(path, "{}\n")
        repo.git("add", "-f", "--", path)
    r = repo.git("commit", "-q", "-m", "t", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "profiles.json" in out and "santa/web/profiles.json" in out


@pytest.mark.parametrize("path", ALLOWED)
def test_ordinary_and_example_paths_pass(repo, path):
    repo.write(path, "harmless\n")
    rc, out = repo.commit(path)
    assert rc == 0, out


def test_removing_a_private_file_from_the_index_is_allowed(repo):
    repo.write("notes/x.md", "x\n")
    repo.git("add", "-f", "notes/x.md")
    repo.git("commit", "-q", "--no-verify", "-m", "oops")
    repo.git("rm", "-q", "--cached", "notes/x.md")
    r = repo.git("commit", "-q", "-m", "cleanup", check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_renamed_in_private_path_is_blocked(repo):
    repo.write("ok.txt", "some content that is long enough to be a rename\n" * 5)
    repo.git("add", "ok.txt")
    repo.git("commit", "-q", "-m", "ok")
    (repo.dir / "notes").mkdir()
    repo.git("mv", "ok.txt", "notes/ok.txt")
    r = repo.git("commit", "-q", "-m", "mv", check=False)
    assert r.returncode != 0 and "notes/ok.txt" in r.stdout + r.stderr


def test_a_tracked_private_file_moved_to_an_allowed_path_is_blocked(repo):
    """P10b-2: a pure rename has no added lines, so the move must count as a full add."""
    repo.write("notes/k.md", f"some line\nthe name {NAME_CI} here\nmore text\n")
    repo.git("add", "-f", "notes/k.md")
    repo.commit_unhooked("planted")
    (repo.dir / "docs").mkdir()
    repo.git("mv", "notes/k.md", "docs/k.md")
    r = repo.git("commit", "-q", "-m", "mv", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "docs/k.md:2" in out and "ci" in out, out
    assert NAME_CI not in out.lower(), "the hook printed the matching text"
    assert repo.git("rev-list", "--count", "HEAD").stdout.strip() == "2"


# ------------------------------------------------------------------------------------- (b) personal data
def test_added_line_with_ci_term_is_blocked_case_insensitively_and_value_is_not_printed(repo):
    repo.write("a.txt", f"fine\nHello {NAME_CI.upper()} there\n")
    rc, out = repo.commit("a.txt")
    assert rc != 0
    assert "a.txt:2" in out and "ci" in out
    assert NAME_CI not in out.lower(), "the hook printed the matching text"


def test_whole_word_only(repo):
    repo.write("a.txt", f"x{NAME_CI}y and {NAME_CI}s\n")
    rc, out = repo.commit("a.txt")
    assert rc == 0, out


def test_cs_file_blocks_title_case_but_lets_the_lowercase_word_through(repo):
    repo.write("ok.txt", f"{NAME_CS.lower()} is an ordinary word\n")
    rc, out = repo.commit("ok.txt")
    assert rc == 0, out
    repo.write("bad.txt", f"one\ntwo\n{NAME_CS} was here\n")
    rc, out = repo.commit("bad.txt")
    assert rc != 0
    assert "bad.txt:3" in out and "cs" in out
    assert NAME_CS.lower() not in out.lower(), "the hook printed the matching text"


@pytest.mark.parametrize("esc", ["\\n", "\\r", "\\t"])
@pytest.mark.parametrize("which", ["ci", "cs"])
def test_term_right_after_a_json_escape_is_blocked(repo, which, esc):
    """P10b-3: the letter of a literal backslash-n/r/t escape must not hide the following word."""
    name = NAME_CI if which == "ci" else NAME_CS
    repo.write("a.json", '{"ok":1}\n{"t":"hi' + esc + name + '"}\n')
    rc, out = repo.commit("a.json")
    assert rc != 0, out
    assert "a.json:2" in out and which in out, out
    assert name.lower() not in out.lower(), "the hook printed the matching text"


@pytest.mark.parametrize("name", [NAME_CI, NAME_CS])
def test_letters_n_r_t_before_a_term_in_an_ordinary_word_still_do_not_match(repo, name):
    """The escape fix must not turn the whole-word rule into a substring rule."""
    repo.write("a.txt", f"in{name} or r{name} and t{name} and n{name}x\n")
    rc, out = repo.commit("a.txt")
    assert rc == 0, out


def test_line_number_is_the_new_file_line_number(repo):
    repo.write("a.txt", "".join(f"line {i}\n" for i in range(1, 11)))
    repo.git("add", "a.txt")
    repo.commit_unhooked("a")
    lines = (repo.dir / "a.txt").read_text().splitlines()
    lines.insert(6, f"inserted {NAME_CI}")          # becomes line 7
    repo.write("a.txt", "\n".join(lines) + "\n")
    rc, out = repo.commit("a.txt")
    assert rc != 0 and "a.txt:7" in out, out


def test_unchanged_preexisting_term_line_does_not_block_an_unrelated_change(repo):
    repo.write("old.txt", f"before\n{NAME_CI} was already here\nafter\n")
    repo.git("add", "old.txt")
    repo.commit_unhooked("old")
    repo.write("old.txt", f"before\n{NAME_CI} was already here\nafter, changed\n")
    rc, out = repo.commit("old.txt")
    assert rc == 0, out
    repo.write("other.py", "print('hi')\n")
    rc, out = repo.commit("other.py")
    assert rc == 0, out


def test_deleting_a_line_that_contains_a_term_is_allowed(repo):
    repo.write("old.txt", f"keep\n{NAME_CI} here\n")
    repo.git("add", "old.txt")
    repo.commit_unhooked("old")
    repo.write("old.txt", "keep\n")
    rc, out = repo.commit("old.txt")
    assert rc == 0, out


def test_binary_files_are_skipped(repo):
    repo.write("b.bin", b"\x00\x01" + NAME_CI.encode() + b"\x00\x02\n", binary=True)
    rc, out = repo.commit("b.bin")
    assert rc == 0, out


def test_term_in_a_commit_that_touches_two_files_names_the_right_one(repo):
    repo.write("clean.txt", "nothing\n")
    repo.write("dirty.txt", f"x\n{NAME_CI}\n")
    repo.git("add", "clean.txt", "dirty.txt")
    r = repo.git("commit", "-q", "-m", "t", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "dirty.txt:2" in out and "clean.txt" not in out


@pytest.mark.parametrize("which", ["ci", "cs"])
@pytest.mark.parametrize("blank", ["\n", "   \n", "\t\n"])
def test_blank_line_in_a_term_file_blocks(repo, which, blank):
    f = repo.ci if which == "ci" else repo.cs
    f.write_text(f.read_text() + blank)
    repo.write("a.py", "print('nothing personal')\n")
    rc, out = repo.commit("a.py")
    assert rc != 0, out
    assert "empty" in out.lower() or "blank" in out.lower()
    assert str(f) in out


def test_missing_term_files_do_not_block_and_say_so_once_each(repo):
    repo.ci.unlink()
    repo.cs.unlink()
    repo.write("a.py", "print('hi')\n")
    rc, out = repo.commit("a.py")
    assert rc == 0, out
    assert out.lower().count("not found") == 2 or out.lower().count("missing") == 2, out


def test_default_term_files_are_read_from_home_when_the_env_vars_are_unset(repo):
    (repo.home / ".santa-pii-terms.txt").write_text(NAME_CI + "\n")
    repo.write("a.txt", f"{NAME_CI}\n")
    repo.git("add", "a.txt")
    env = repo.env()
    del env["SANTA_PII_TERMS"], env["SANTA_PII_TERMS_CS"]
    r = subprocess.run(["git", "commit", "-q", "-m", "t"], cwd=repo.dir, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "a.txt:1" in r.stdout + r.stderr


# ------------------------------------------------------------------------------------- SKIP_GITLEAKS
def test_skip_gitleaks_still_allows_a_clean_commit(repo):
    repo.write("a.py", "print('hi')\n")
    rc, out = repo.commit("a.py", SKIP_GITLEAKS="1")
    assert rc == 0, out


def test_skip_gitleaks_does_not_bypass_the_private_path_block(repo):
    repo.write("notes/x.md", "x\n")
    rc, out = repo.commit("notes/x.md", force=True, SKIP_GITLEAKS="1")
    assert rc != 0 and "notes/x.md" in out


def test_skip_gitleaks_does_not_bypass_the_personal_data_block(repo):
    repo.write("a.txt", f"{NAME_CI}\n")
    rc, out = repo.commit("a.txt", SKIP_GITLEAKS="1")
    assert rc != 0 and "a.txt:1" in out
    assert NAME_CI not in out.lower()
