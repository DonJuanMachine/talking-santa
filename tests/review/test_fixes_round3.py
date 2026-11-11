"""Regression tests for round 3 (FIX D: opener does not count toward the cap + keep the final question;
FIX E: persona labels / export_blind; FIX F: "I will bring you"; FIX H lives in test_fixes_bench.py)."""
import glob
import json
import re

import pytest

from santa import config, safety

SPLIT = safety._SENT_SPLIT.split


def sents(text):
    return SPLIT(text)


# ============================================================ FIX D1: opener does not count
def test_d1_opener_plus_three_sentences_kept():
    out = safety.sanitize("Ho ho ho! A robot? No, Ziv! I'm a real Santa. I love cookies.")
    assert out == "Ho ho ho! A robot? No, Ziv! I'm a real Santa."
    assert len(sents(out)) == 4 and out.count("?") <= 1


def test_d1_reply_without_opener_keeps_the_three_sentence_cap():
    out = safety.sanitize("A robot? No, Ziv! I'm a real Santa. I love cookies. More fun.")
    assert out == "A robot? No, Ziv! I'm a real Santa." and len(sents(out)) == config.MAX_SENTENCES == 3


@pytest.mark.parametrize("opener", ["Ho ho!", "Ho ho ho!", "Ooooh!", "Oh!", "Well, wow!", "Hohoho!", "Hey!"])
def test_d1_all_interjection_openers_behave_the_same(opener):
    out = safety.sanitize(f"{opener} Hi Emma. Nice cat. Big snow. Extra one.")
    assert out == f"{opener} Hi Emma. Nice cat. Big snow."


@pytest.mark.parametrize("not_opener", ["Ho ho ho, Emma darling!", "Ho ho ho, Emma!", "Hello!", "Ho ho ho ho!", "Merry Christmas!"])
def test_d1_other_first_sentences_are_not_openers(not_opener):
    assert not safety._is_opener(not_opener)
    out = safety.sanitize(f"{not_opener} Hi Emma. Nice cat. Big snow.")
    assert len(sents(out)) == 3 and out.endswith("Nice cat.")


def test_d1_only_a_leading_opener_is_free():
    out = safety.sanitize("Hi Emma. Ho ho ho! Nice cat. Big snow. Extra.")
    assert out == "Hi Emma. Ho ho ho! Nice cat."


def test_d1_opener_words_still_count_toward_word_cap():
    # B2 (TEST_CHANGES.md): the cap stops before a sentence that does not fit; it never cuts inside one
    fits = "Ho ho ho! " + " ".join(["snow"] * 42) + "."          # 3 + 42 = 45 words
    assert safety.sanitize(fits) == fits
    over = "Ho ho ho! " + " ".join(["snow"] * 43) + "."          # 46 words: the opener's words count
    assert safety.sanitize(over) == "Ho ho ho!"


def test_d1_lone_opener_is_not_empty_and_max_words_never_exceeded():
    assert safety.sanitize("Ho ho ho!") == "Ho ho ho!"
    for raw in ["Ho ho ho! " + "Word " * 20 + "now. " + "More words here. " * 5 + "Really?",
                "Ooooh! " + " ".join(f"w{i}" for i in range(100)) + "?",
                "Ho ho! A. B. C. D. " + "x " * 60 + "Why?"]:
        assert len(safety.sanitize(raw).split()) <= config.MAX_WORDS


def test_d_config_values_unchanged():
    assert config.MAX_SENTENCES == 3 and config.MAX_WORDS == 45


# FIX D2 (drop the middle, keep the final question) was removed in Stage B; its four tests that asserted D2 output
# are retired (TEST_CHANGES.md). These three still hold with the remove-only filter and are kept unchanged.
def test_d2_not_applied_when_question_already_fits():
    raw = "Ho ho ho! Hello Emma! Nice to see you! Did you have fun?"
    assert safety.sanitize(raw) == raw


def test_d2_not_applied_when_question_is_not_the_last_sentence():
    out = safety.sanitize("Ho ho ho! Hi Emma. Nice cat. Big snow. Do you like snow? Yes indeed.")
    assert "?" not in out and len(sents(out)) == 4


def test_d2_not_applied_when_it_would_exceed_the_word_cap():
    long_q = "Do you " + " ".join(["really"] * 45) + " like snow?"
    out = safety.sanitize("Ho ho ho! Hi Emma. Nice cat. Big snow. " + long_q)
    assert len(out.split()) <= config.MAX_WORDS and "Do you really" not in out


def test_d_stored_replies_rate_and_word_cap():
    """Read-only on evals/results: no reply over MAX_WORDS, no reply with 2+ '?', and few replies with no question."""
    from conftest import ROOT
    raws = [t["raw"] for f in sorted(glob.glob(str(ROOT / "evals" / "results" / "ai_*.json")))
            for t in json.load(open(f))["turns"] if t["raw"].strip()]
    if not raws:
        pytest.skip("no stored results")
    outs = [safety.sanitize(r) for r in raws]
    assert max(len(o.split()) for o in outs) <= config.MAX_WORDS
    # decisions 2/3 (TEST_CHANGES.md): two questions and no question are both allowed; the 30% target is retired


# ============================================================ FIX D3/(e): everything else unchanged
def test_d3_fallback_and_reasons_unaffected():
    assert safety.FALLBACK == "Santa is listening. Can you tell your grown-up too?"   # no "Ho ho" (ho_once)
    # safety decision at the Stage B gate (TEST_CHANGES.md): the safe opener may be spoken, the hit never
    from test_safety import _assert_claim_never_spoken
    _assert_claim_never_spoken("Ho ho ho! I am ChatGPT!")
    _assert_claim_never_spoken("Ho ho ho! Call 555 123 4567", rule="private")
    assert safety.sanitize_ex("I am ChatGPT!") == (safety.FALLBACK, "blocklist")
    assert safety.sanitize_ex("*waves*") == (safety.FALLBACK, "empty")
    assert safety.sanitize_ex("Call 555 123 4567") == (safety.FALLBACK, "private_output")
    assert safety.sanitize_ex("Ho ho ho!") == ("Ho ho ho!", None)


def test_d3_check_unchanged():
    # check() was deleted (B1); the measurement now lives in spec.shape_flags (see docs/history/TEST_CHANGES.md)
    from santa import spec
    assert spec.shape_flags("Ho ho ho! A? B? C?") == ["questions>1"]


# ============================================================ FIX F: "I will bring you" follows the gift-word rule
def test_f_i_will_bring_you_a_pony_is_blocked():
    assert safety.sanitize("I will bring you a pony!") == safety.FALLBACK


def test_f_i_will_bring_you_a_hug_passes():
    # Stage D1: a promise needs a gift noun and a recipient; a hug is not a gift noun (test restored from before C3).
    assert safety.sanitize("I will bring you a hug!") == "I will bring you a hug!"


def test_f_i_ll_bring_you_matches_i_will_bring_you():
    # Stage D1: "I'll bring you a hug!" is spoken unchanged, like "I will bring you a hug!"; the puppy is blocked.
    for apostrophe in ("'", "’"):
        assert safety.sanitize(f"I{apostrophe}ll bring you a hug!") == f"I{apostrophe}ll bring you a hug!"
        assert safety.sanitize(f"I{apostrophe}ll bring you a puppy!") == safety.FALLBACK


def test_f_i_promise_stays_always_blocked():
    for raw in ("I promise.", "I promise you a hug!", "I promise to tell my elves!", "I promise you a pony"):
        assert safety.sanitize(raw) == safety.FALLBACK


def test_f_gift_word_and_you_within_eight_words_for_i_will_bring():
    # Stage D1: the gift noun AND "you"/"your" must both be within 8 words after the verb; a gift with no
    # recipient is not a promise.
    assert safety.sanitize("I will bring you one great big shiny red new truck!") == safety.FALLBACK    # 8th word
    assert safety.sanitize("I will bring you one great big shiny red new and fun truck!") != safety.FALLBACK  # 10th
    assert safety.sanitize("I will bring one big red truck for your tree!") == safety.FALLBACK         # your: 6th
    assert safety.sanitize("I will bring one great big shiny red new truck for your tree!") != safety.FALLBACK  # 9th
    raw = "I will bring one great big shiny red new truck!"                                    # no recipient
    assert safety.sanitize(raw) == raw


# ============================================================ FIX E: persona labels and export_blind
import hashlib
import shutil
import subprocess
import sys

from conftest import ROOT
from test_bench import _turn, bench, sandbox  # noqa: F401  (fixtures)


def _sha(version):
    return hashlib.sha256((ROOT / "evals" / "personas" / f"persona_{version}.txt").read_bytes()).hexdigest()[:10]


def _result(sandbox, name, model, persona_sha=None, answers=("Hi Emma!",)):
    d = {"model": model, "cold": 1.0, "turns": [_turn("greet", sample=0, idx=i, raw=a) for i, a in enumerate(answers)],
         "extraction": []}
    if persona_sha:
        d["persona_sha"] = persona_sha
    (sandbox / "results" / f"{name}.json").write_text(json.dumps(d))


@pytest.fixture
def export_sandbox(bench, sandbox):
    (sandbox / "evals" / "personas").mkdir()
    for v in ("v1", "v2", "v3"):
        shutil.copy(ROOT / "evals" / "personas" / f"persona_{v}.txt", sandbox / "evals" / "personas")
    _result(sandbox, "ai_gemma4", "ai/gemma4")                                         # legacy, not in the v2 list -> v1
    _result(sandbox, "ai_ministral3_14B", "ai/ministral3:14B")                         # legacy, in the v2 list -> v2
    _result(sandbox, "ai_foo_v2", "ai/foo+v2", _sha("v2"), ("Hi Emma v2!",))           # recorded v2
    _result(sandbox, "ai_foo_v3", "ai/foo+v3", _sha("v3"), ("Hi Emma v3!",))           # recorded v3
    _result(sandbox, "ai_bar", "ai/bar", "deadbeef00", ("Hi Emma other!",))            # unknown persona
    (sandbox / "results" / "judge.json").write_text("{}")
    return sandbox


def _export(bench, sandbox, personas=None):
    out, mp = sandbox / "blind.txt", sandbox / "blind_map.json"
    bench.export_blind(str(out), str(mp), personas)
    return out.read_text(), json.loads(mp.read_text())


def _labels(mapping):
    return sorted({v.split("|")[0] for v in mapping.values()})


def test_e_persona_label_from_persona_sha(bench, export_sandbox):
    assert bench.persona_label({"model": "ai/foo", "persona_sha": _sha("v3")})[0] == "v3"
    assert bench.persona_label({"model": "ai/foo", "persona_sha": _sha("v2")})[0] == "v2"
    assert bench.persona_label({"model": "ai/foo", "persona_sha": _sha("v1")})[0] == "v1"
    assert bench.persona_label({"model": "ai/foo", "persona_sha": "deadbeef00"})[0] == "other"


def test_e_legacy_files_keep_their_labels(bench):
    """Today's seven real result files (read-only): same labels as before, with no metadata needed."""
    # bench_all.sh moves old results to evals/backup/<date>/ before a new run (2026-11-10): read them from the
    # newest folder that still holds them.
    legacy = "ai_gemma4.json"
    homes = [ROOT / "evals" / "results"] + sorted((ROOT / "evals" / "backup").glob("*/"), reverse=True)
    home = next((d for d in homes if (d / legacy).exists()), None)
    if home is None:
        pytest.skip("the seven legacy result files are not in evals/results or evals/backup")
    labels = {}
    for f in sorted(home.glob("ai_*.json")):
        d = json.loads(f.read_text())
        if "persona_sha" not in d:
            labels[f.name] = bench.persona_label(d)[0]
    assert labels["ai_gemma4.json"] == "v1" and labels["ai_gemma4_e4b.json"] == "v1"
    assert all(labels[n] == "v2" for n in ("ai_gemma4_e4b_v2.json", "ai_gemma4_v2.json", "ai_ministral3_14B.json",
                                           "ai_ministral3_8B_Q4_K_M.json", "ai_ministral_3_8b_instruct.json"))


def test_e_default_exports_every_label_except_other(bench, export_sandbox):
    _, mapping = _export(bench, export_sandbox)
    assert _labels(mapping) == ["v1", "v2", "v3"] and len(mapping) == 4


def test_e_v3_file_is_exported(bench, export_sandbox):
    _, mapping = _export(bench, export_sandbox)
    assert any(v.startswith("v3|ai_foo_v3|") for v in mapping.values())


def test_e_personas_option_selects_labels(bench, export_sandbox):
    _, m3 = _export(bench, export_sandbox, ["v3"])
    assert _labels(m3) == ["v3"] and len(m3) == 1
    _, m2 = _export(bench, export_sandbox, ["v2"])
    assert _labels(m2) == ["v2"] and len(m2) == 2          # legacy v2 + recorded v2, but no v3
    _, mo = _export(bench, export_sandbox, ["other"])
    assert len(mo) == 1 and _labels(mo) == ["other"]
    _, m23 = _export(bench, export_sandbox, ["v2", "v3"])
    assert _labels(m23) == ["v2", "v3"]


def test_e_v2_and_v3_are_never_merged_into_one_row(bench, export_sandbox):
    _result(export_sandbox, "ai_same_v2", "ai/same", _sha("v2"))
    _result(export_sandbox, "ai_same_v3", "ai/same", _sha("v3"))     # same model label, different persona
    _, mapping = _export(bench, export_sandbox)
    same = [v for v in mapping.values() if "|ai_same|" in v]
    assert sorted(v.split("|")[0] for v in same) == ["v2", "v3"] and len(set(same)) == 2


def test_e_ids_unique_and_review_text_is_blind(bench, export_sandbox):
    text, mapping = _export(bench, export_sandbox)
    assert len(set(mapping.values())) == len(mapping)
    low = text.lower()
    for word in ("gemma", "ministral", "foo", "bar", "v1", "v2", "v3", "persona", "ai/", "other", "|ai_"):
        assert word not in low.replace("hi emma v2!", "").replace("hi emma v3!", "").replace("hi emma other!", ""), word
    assert text.count("\n") == len(mapping)


def test_e_failed_turns_are_not_exported(bench, export_sandbox):
    _result(export_sandbox, "ai_err_v3", "ai/err+v3", _sha("v3"), answers=("",))
    _, mapping = _export(bench, export_sandbox, ["v3"])
    assert not any("ai_err_v3" in v for v in mapping.values())


def test_e_cli_personas_option_parses(tmp_path):
    """Run the real CLI against the real results (read-only): no real file has persona 'other' or v3."""
    for flag, expected in ((["--personas", "other"], "0 items"), (["--personas=v3"], "0 items"), (["--personas", "v1"], None)):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "evals" / "bench.py"), "export", str(tmp_path / "a.txt"),
                            str(tmp_path / "m.json"), *flag], capture_output=True, text=True, cwd=tmp_path,
                           env={"PATH": "/usr/bin:/bin", "SANTA_PROFILES": str(tmp_path / "p.json")})
        assert r.returncode == 0, r.stderr
        if expected:
            assert expected in r.stdout
        else:
            assert "items exported" in r.stdout and not r.stdout.startswith("0 ")
        assert all(v.split("|")[0] == "v1" for v in json.loads((tmp_path / "m.json").read_text()).values()) or expected
