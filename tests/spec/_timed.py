"""Timing cases that FAIL instead of hanging (P7-6).

A catastrophic regex never returns, so timing it in the test process stalls the suite (and a pre-commit run) with no
message. timed() runs the calls in a child process that is killed after CHILD_TIMEOUT_S; the child reports each call's
own time and result, so the tests keep their bounds, and a kill fails the test naming the call that was running.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHILD_TIMEOUT_S = 5.0      # interpreter start and import included; every case here needs well under a second

_CHILD = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
sys.dont_write_bytecode = True
from santa import spec, speech
FUNCS = {"safety_reason": spec.safety_reason, "strip_ho": spec.strip_ho, "is_gift_turn": speech.is_gift_turn}
for i, (fn, text, kw) in enumerate(json.loads(sys.stdin.read())):
    print(json.dumps({"start": i}), flush=True)
    t0 = time.perf_counter()
    r = FUNCS[fn](text, **kw)
    print(json.dumps({"done": i, "s": time.perf_counter() - t0, "result": r}), flush=True)
"""


def _lines(out):
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    return [json.loads(ln) for ln in (out or "").splitlines() if ln.startswith("{")]


def timed(calls, timeout=CHILD_TIMEOUT_S):
    """calls: [(function name, text, kwargs)] with function name one of safety_reason, strip_ho, is_gift_turn.
    Returns [(seconds, result)] in order. Fails the test if the child is not done within `timeout` seconds."""
    calls = [(fn, text, dict(kw or {})) for fn, text, kw in calls]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run([sys.executable, "-c", _CHILD, str(ROOT)], input=json.dumps(calls), capture_output=True,
                           text=True, timeout=timeout, env=env, cwd=str(ROOT))
    except subprocess.TimeoutExpired as e:
        started = [m["start"] for m in _lines(e.stdout) if "start" in m]
        if started:
            fn, text, kw = calls[started[-1]]
            where = f"{fn}({text[:60]!r}{'...' if len(text) > 60 else ''}, {kw})"
        else:
            where = "start-up (no call had started)"
        pytest.fail(f"killed after {timeout} s, still inside {where}: catastrophic backtracking?", pytrace=False)
    assert r.returncode == 0, r.stderr[-2000:]
    done = [m for m in _lines(r.stdout) if "done" in m]
    assert [m["done"] for m in done] == list(range(len(calls))), r.stdout[-2000:]
    return [(m["s"], m["result"]) for m in done]
