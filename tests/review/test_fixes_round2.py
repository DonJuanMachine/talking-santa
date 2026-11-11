"""Regression tests for round 2 (FIX A: one question before the cap + persona v3; FIX B: warm-up; FIX C: blocklist)."""
import re

import pytest

from santa import persona, safety

ECHO = "Ho ho ho! Mittens, you said? I remember sweet Mittens! Do you like the twinkly lights?"


def _sentences(text):
    return safety._SENT_SPLIT.split(text)


# ============================================================ FIX A
# B2 + decisions 2/3 (TEST_CHANGES.md): questions are never demoted; the cap only removes whole trailing sentences.
def test_a_real_question_survives_the_cap_when_it_fits():
    raw = "Mittens, you said? I remember sweet Mittens! Do you like the twinkly lights?"
    assert safety.sanitize(raw) == raw
    raw = "Ho ho! Mittens, you said? Do you like the twinkly lights?"
    assert safety.sanitize(raw) == raw


def test_a_only_cap_removes_sentences():
    out = safety.sanitize(ECHO)
    raw = _sentences(ECHO)
    kept = _sentences(out)
    assert kept == raw[:len(kept)] and len(kept) <= 4      # a prefix of the same sentences, nothing reworded


def test_a_five_sentences_three_questions():
    for raw in ("Wow? Ho ho ho! Do you like snow? I love snow! Do you like sleds?",
                "Do you like snow? Ho ho! Do you like sleds? Yes! Do you like cookies?"):
        out = safety.sanitize(raw)
        kept = _sentences(out)
        assert kept == _sentences(raw)[:len(kept)] and len(kept) <= 4 and out.count("?") <= raw.count("?")


def test_a_three_sentences_keep_all_and_exactly_one_question():
    raw = "Mittens, you said? I remember her! Do you like lights?"
    assert safety.sanitize(raw) == raw


def test_a_reply_may_end_with_no_question():
    out = safety.sanitize("Ho ho ho! Hi Emma, you said? I love that. Wow! Do you like snow?")
    assert out == "Ho ho ho! Hi Emma, you said? I love that. Wow!"   # the cap cut the final question; that is allowed


def test_a_greetings_are_not_special_cased():
    raw = "Who am I talking to? Is there a little friend there with me?"
    assert safety.sanitize(raw) == raw


def test_a_word_cap_cannot_leave_two_questions():
    raw = "Do you like snow? " + " ".join(["fun"] * 50) + "? Really?"
    assert safety.sanitize(raw).count("?") <= 1


def test_a_check_still_flags_multiple_questions_on_raw():
    # check() was deleted (B1); the measurement now lives in spec.shape_flags (see docs/history/TEST_CHANGES.md)
    from santa import spec
    assert "questions>1" in spec.shape_flags(ECHO)


def test_a_persona_v1_file_equals_santa_prompt_and_v2_v3_are_untouched():
    # decision 1 (TEST_CHANGES.md): SANTA_PROMPT is an exact copy of persona_v1.txt; the persona files are unchanged
    from conftest import ROOT
    import hashlib
    assert (ROOT / "evals" / "personas" / "persona_v1.txt").read_text() == persona.SANTA_PROMPT
    assert hashlib.sha256((ROOT / "evals" / "personas" / "persona_v2.txt").read_bytes()).hexdigest()[:10] == "0bb1e50fc9"
    assert "FIRST react" in (ROOT / "evals" / "personas" / "persona_v3.txt").read_text()


# ============================================================ FIX B: warm-up and timeouts
import json
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from openai import Timeout

import santa.brain as brain
from santa import config
from conftest import ROOT, FakeClient
from test_bench import FakeSanta, bench, sandbox  # noqa: F401  (fixtures)


class WarmClient(FakeClient):
    """FakeClient that also supports client.with_options(timeout=...) and records warm-up calls separately."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.events, self.warm_calls, self.option_timeouts, self.warm_error = [], [], [], None

    def _create(self, **kw):
        self.events.append("stream" if kw.get("stream") else "extract")
        return super()._create(**kw)

    def with_options(self, **opts):
        self.option_timeouts.append(opts.get("timeout"))
        outer = self

        def create(**kw):
            outer.events.append("warm")
            outer.warm_calls.append(kw)
            if outer.warm_error:
                raise outer.warm_error
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="h"))])

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.fixture
def warm_santa(make_santa):
    s = make_santa()
    s.client = WarmClient()
    return s


def test_b_config_defaults_and_env_overrides():
    code = "from santa import config as c; print(c.REQUEST_TIMEOUT, c.WARMUP_TIMEOUT, c.IDLE_REWARM_SECONDS)"
    run = lambda env: subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r}); " + code],  # noqa: E731
                                     capture_output=True, text=True, env=env).stdout.split()
    assert run({"PATH": "/usr/bin:/bin"}) == ["15.0", "90.0", "300.0"]
    assert run({"PATH": "/usr/bin:/bin", "SANTA_TIMEOUT": "7", "SANTA_WARMUP_TIMEOUT": "120",
                "SANTA_IDLE_REWARM": "60"}) == ["7.0", "120.0", "60.0"]


def test_b_normal_client_keeps_short_timeout_and_no_retries(tmp_profiles):
    s = brain.Santa(model="m", base_url="http://127.0.0.1:9/v1")
    assert s.client.timeout.read == config.REQUEST_TIMEOUT == 15.0 and s.client.max_retries == 0


def test_b_warm_up_uses_long_timeout_and_one_token(warm_santa):
    assert warm_santa.warm_up() is True
    c = warm_santa.client
    assert c.option_timeouts[0].read == config.WARMUP_TIMEOUT == 90.0
    assert c.warm_calls[0]["max_tokens"] == 1 and not c.warm_calls[0].get("stream")
    assert warm_santa.last_ok_time is not None and warm_santa.last_warmup_seconds >= 0
    assert not c.calls            # the warm-up is not a Santa/extractor call


def test_b_warm_up_never_raises_and_does_not_hide_the_error(warm_santa):
    warm_santa.client.warm_error = ConnectionError("model runner down")
    assert warm_santa.warm_up() is False
    assert warm_santa.last_error.startswith("warmup_error: ConnectionError")
    assert warm_santa.last_ok_time is None and warm_santa.last_warmup_seconds is not None


def test_b_warm_up_survives_even_a_client_without_with_options(make_santa):
    s = make_santa()                      # plain FakeClient has no with_options
    assert s.warm_up() is False and s.last_error.startswith("warmup_error")


def test_b_warm_up_against_a_dead_port_returns_false(tmp_profiles):
    s = brain.Santa(model="m", base_url="http://127.0.0.1:9/v1")
    assert s.warm_up() is False and "warmup_error" in s.last_error


class _HangingServer:
    """Accepts connections and never answers. Counts them (a retry would show up as a second connection)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.connections, self.held = 0, []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            self.held.append(c)

    def close(self):
        self.sock.close()
        for c in self.held:
            c.close()


@pytest.fixture
def hanging_server():
    srv = _HangingServer()
    yield srv
    srv.close()


def test_b_warm_up_timeout_is_the_warmup_one_not_the_normal_one(tmp_profiles, hanging_server, monkeypatch):
    monkeypatch.setattr(config, "WARMUP_TIMEOUT", 0.4)
    s = brain.Santa(model="m", base_url=f"http://127.0.0.1:{hanging_server.port}/v1")
    t0 = time.perf_counter()
    assert s.warm_up() is False
    assert time.perf_counter() - t0 < 5 and "APITimeoutError" in s.last_error   # normal timeout would be 15 s
    assert hanging_server.connections == 1


def test_b_timeout_in_normal_reply_returns_fallback_and_does_not_retry(tmp_profiles, hanging_server):
    s = brain.Santa(model="m", base_url=f"http://127.0.0.1:{hanging_server.port}/v1")
    s.profiles = {"Emma": {"facts": []}}
    s.client = s.client.with_options(timeout=0.4)       # shrink 15 s so the test is fast; retries stay at 0
    assert s.client.max_retries == 0
    s.last_ok_time = brain._now()                       # recently used: no warm-up first
    t0 = time.perf_counter()
    out = s.reply("Emma", "hi santa")
    assert time.perf_counter() - t0 < 5
    assert out == safety.FALLBACK and s.last_error.startswith("model_error: APITimeoutError")
    assert s.last_stats["error"] is True and hanging_server.connections == 1


def test_b_reply_warms_up_first_when_idle_and_not_when_recent(warm_santa, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(brain, "_now", lambda: clock[0])
    s = warm_santa
    s.reply("Emma", "one")                                  # never used: warm first
    assert s.client.events[:2] == ["warm", "stream"] and s.last_ok_time == 1000.0
    clock[0] = 1000 + config.IDLE_REWARM_SECONDS - 1
    s.reply("Emma", "two")                                  # recent: no warm-up
    assert s.client.events.count("warm") == 1
    clock[0] = 1000 + config.IDLE_REWARM_SECONDS - 1 + config.IDLE_REWARM_SECONDS + 1
    s.reply("Emma", "three")                                # idle too long: warm again, BEFORE the request
    ev = [e for e in s.client.events if e != "extract"]
    assert ev.count("warm") == 2 and ev[-2:] == ["warm", "stream"]


def test_b_failed_warm_up_does_not_stop_the_reply(warm_santa):
    warm_santa.client.warm_error = TimeoutError("slow")
    assert warm_santa.reply("Emma", "hi") == "Hello there!"     # "Ho ho ho!" removed: Santa laughs once (ho_once)
    assert warm_santa.last_error is None


def test_b_successful_reply_refreshes_last_ok_time_but_a_model_error_does_not(make_santa, monkeypatch):
    clock = [50.0]
    monkeypatch.setattr(brain, "_now", lambda: clock[0])
    s = make_santa(replies=["Hi!", RuntimeError("boom")])
    s.reply("Emma", "a")
    assert s.last_ok_time == 50.0
    clock[0] = 60.0
    s.reply("Emma", "b")
    assert s.last_ok_time == 50.0


# ---- bench: cold load is the warm-up time; judge model is warmed too
class WarmFakeSanta(FakeSanta):
    warm_ok, warmed = True, []

    def warm_up(self):
        type(self).warmed.append(self.model)
        self.last_warmup_seconds = 4.25
        self.last_error = None if self.warm_ok else "warmup_error: boom"
        return self.warm_ok


def test_b_bench_cold_load_is_the_warm_up_time(bench, sandbox, monkeypatch):
    WarmFakeSanta.warmed = []
    monkeypatch.setattr(bench, "Santa", WarmFakeSanta)
    bench.gen("fake/model")
    assert json.loads((sandbox / "results" / "fake_model.json").read_text())["cold"] == 4.25
    assert WarmFakeSanta.warmed[0] == "fake/model"


def test_b_bench_gen_stops_when_the_model_will_not_load(bench, sandbox, monkeypatch):
    monkeypatch.setattr(bench, "Santa", WarmFakeSanta)
    monkeypatch.setattr(WarmFakeSanta, "warm_ok", False)
    with pytest.raises(RuntimeError, match="warm-up of fake/model failed"):
        bench.gen("fake/model")
    assert not list((sandbox / "results").glob("*.json"))


def test_b_bench_judge_warms_the_judge_model(bench, sandbox, monkeypatch):
    from test_bench import _turn, _write
    WarmFakeSanta.warmed = []
    monkeypatch.setattr(bench, "Santa", WarmFakeSanta)
    _write(sandbox, "m", [_turn("a")])
    bench.judge("some-judge-model")
    assert WarmFakeSanta.warmed == ["some-judge-model"]


def test_b_chat_warms_up_before_the_greeting(tmp_path, hanging_server):
    env = {"PATH": "/usr/bin:/bin", "SANTA_PROFILES": str(tmp_path / "p.json"),
           "SANTA_BASE_URL": "http://127.0.0.1:9/v1", "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, str(ROOT / "chat.py")], input="/quit\n", capture_output=True, text=True,
                       env=env, cwd=tmp_path, timeout=60)
    out = r.stdout
    assert out.index("Loading Santa...") < out.index("Santa: Ho ho ho! Merry Christmas!")
    assert "WARNING: the model did not answer" in out


# ============================================================ FIX C: blocklist
@pytest.mark.parametrize("raw", [
    "You'll get a big hug!", "You will get lots of cookies!", "You’ll get a big smile from me!",
    "You will get to ride in the sleigh!", "I'll bring you lots of snowflakes!",   # snowflakes: restored in D1
])
def test_c1_harmless_promises_are_not_blocked(raw):
    assert safety.sanitize(raw) == raw


@pytest.mark.parametrize("raw", [
    "You will get a pony!", "I'll bring you a puppy!", "You’ll get a shiny new bike for Christmas!",
    "You will receive a present!", "You'll receive a big red truck!", "I will bring you a toy dinosaur!",
    "I promise you a pony",
])
def test_c1_gift_promises_are_still_blocked(raw):
    assert safety.sanitize(raw) == safety.FALLBACK


def test_c1_gift_word_must_be_within_eight_words():
    # Stage C3 widened the window from 6 to 8 words after the verb.
    assert safety.sanitize("You will get one great big shiny red truck!") == safety.FALLBACK            # 6th word
    assert safety.sanitize("You will get one great big shiny red new truck!") == safety.FALLBACK        # 7th word
    assert safety.sanitize("You will get one great big shiny red new and fun truck!") != safety.FALLBACK  # 9th word


@pytest.mark.parametrize("raw", ["Hello, Gemma!", "Is Gemma here, Ziv?", "Hi Google fans!", "Gemma, you are so kind!",
                                 "I'm Gemma's friend, Leo!", "Santa is not ChatGPT, I'm Santa!",
                                 "No, I'm not a computer, I'm real!"])
def test_c2_brand_mentions_are_not_blocked(raw):
    assert safety.sanitize(raw) == raw


@pytest.mark.parametrize("raw", ["I'm Gemma, made by Google!", "I am ChatGPT!", "Okay! I am ChatGPT!", "My name is Mistral.",
                                 "I was built by Google.", "Gemma here!", "Ho ho! Ministral here, Ziv!", "I'm a Llama.",
                                 "I’m an AI.", "I'm a robot, Ziv."])
def test_c2_brand_claims_are_blocked(raw):
    if raw.startswith(("Okay! ", "Ho ho! ")):   # safe first sentence may be spoken, the claim never (TEST_CHANGES.md)
        from test_safety import _assert_claim_never_spoken
        _assert_claim_never_spoken(raw)
        return
    assert safety.sanitize(raw) == safety.FALLBACK


def test_c_blocked_reason_is_blocklist():
    assert safety.sanitize_ex("I am ChatGPT!")[1] == "blocklist"
    assert safety.sanitize_ex("You will get a pony!")[1] == "blocklist"
    assert safety.sanitize_ex("Hello, Gemma!")[1] is None
