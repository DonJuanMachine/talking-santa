"""Canned lines (section 4.11). Checked with the same rules as model output when this module is imported, rendered
once in the chosen voice and cached (Santa's voice only) in the gitignored settings.canned_dir."""
import hashlib
import json

import numpy as np

from .safe import Spoken, canned

TEXT = {
    "laugh": "Ho, ho, ho!",                    # said once, at the start of the greeting (see GREETING_SAID)
    "greeting": "Hello, hello! It's Santa! Who am I talking to?",
    "say_again": "Hmm, Santa didn't quite hear that. Can you say it again?",
    "still_here": "I'm still here. Take your time.",
    "goodbye": "Bye bye for now! Merry Christmas!",
}

LINES: dict[str, Spoken] = {k: canned(v) for k, v in TEXT.items()}   # raises at import if a line fails a rule

# The greeting opens with Santa's one big laugh. It is voiced on its own, slower and with a pause after it, so it
# sounds like a real belly laugh instead of three quick words. The rest of the call has no "Ho ho" (brain.ho_once).
LAUGH_SPEED = 0.78                          # Kokoro speed for the laugh (normal speech: settings.speed, 0.9)
LAUGH_PAUSE_S = 0.35
GREETING_SAID = f"{TEXT['laugh']} {TEXT['greeting']}"   # what the brain's history records as Santa's first line


def _key(name: str, tts) -> str:
    extra = [TEXT["laugh"], LAUGH_SPEED, LAUGH_PAUSE_S] if name == "greeting" else []
    h = hashlib.sha256(json.dumps([TEXT[name], getattr(tts, "voice", ""), getattr(tts, "speed", ""),
                                   type(tts).__name__, *extra]).encode()).hexdigest()[:16]
    return f"{name}-{h}.npy"


def _laugh_then_greeting(tts) -> np.ndarray:
    slow = getattr(tts, "synth_at", None)          # Kokoro can change speed per line; other voices use their own
    laugh = slow(LINES["laugh"], LAUGH_SPEED) if slow else tts.synth(LINES["laugh"])
    pause = np.zeros(int(getattr(tts, "sr", 24000) * LAUGH_PAUSE_S), dtype=np.float32)
    return np.concatenate([np.asarray(laugh, dtype=np.float32), pause,
                           np.asarray(tts.synth(LINES["greeting"]), dtype=np.float32)])


def render_all(tts, cache_dir) -> dict[str, np.ndarray]:
    """{name: float32 samples}. Uses the cache when the text, voice and speed are unchanged."""
    out = {}
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    for name, line in LINES.items():
        path = cache_dir / _key(name, tts) if cache_dir is not None else None
        if path is not None and path.exists():
            out[name] = np.load(path)
            continue
        if name == "greeting":
            samples = _laugh_then_greeting(tts)
        else:
            samples = np.asarray(tts.synth(line), dtype=np.float32)
        if path is not None:
            np.save(path, samples)
        out[name] = samples
    return out
