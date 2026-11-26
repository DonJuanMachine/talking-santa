"""Text to speech, in-process: Kyutai Pocket TTS by default (voice stuart_bell), or Kokoro-82M v1.0 through kokoro-onnx
(onnxruntime, CPU) with SANTA_TTS=kokoro. Kokoro was chosen in H1; Pocket became the default after the J1 audition.

Only santa.web.safe.Spoken objects are accepted: text that came out of the brain's speech gate, or a canned line that
passed the same rule checks at startup (see safe.py).
"""
from collections import OrderedDict

import numpy as np

from .safe import Spoken, assert_speakable

SR = 24000


def kokoro_voice(spec: str, styles):
    """SANTA_VOICE for Kokoro: one voice name ("am_santa"), or a blend of style vectors written as name:weight pairs
    ("am_santa:70,bm_fable:30"). Weights are normalised to sum to 1. `styles` maps voice names to style arrays.
    Returns the name unchanged for a single voice, else the mixed float32 style array."""
    if ":" not in spec and "," not in spec:
        if spec not in styles:
            raise ValueError(f"unknown Kokoro voice {spec!r}")
        return spec
    parts = []
    for item in spec.split(","):
        name, sep, w = item.strip().partition(":")
        if not sep or name not in styles:
            raise ValueError(f"bad Kokoro blend part {item!r} in {spec!r}: use name:weight with known voice names")
        try:
            weight = float(w)
        except ValueError:
            raise ValueError(f"bad weight in {item!r}") from None
        if weight <= 0:
            raise ValueError(f"weight must be positive in {item!r}")
        parts.append((name, weight))
    if len(parts) < 2:
        raise ValueError(f"a blend needs at least two voices: {spec!r}")
    total = sum(w for _, w in parts)
    return sum((w / total) * np.asarray(styles[n], dtype=np.float32) for n, w in parts).astype(np.float32)


class KokoroTTS:
    sr = SR

    def __init__(self, settings):
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        so = ort.SessionOptions()
        sess = ort.InferenceSession(str(settings.kokoro_model), so, providers=["CPUExecutionProvider"])
        self.k = Kokoro.from_session(sess, str(settings.kokoro_voices))
        self.voice, self.speed = settings.voice, settings.speed     # voice stays the text spec (canned cache key)
        self._style = kokoro_voice(settings.voice, self.k.voices)    # a name, or a mixed style array for a blend
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()   # short repeated lines ("Ho ho ho!"), RAM only

    def synth_at(self, line: Spoken, speed: float) -> np.ndarray:
        """One line at its own speed (Santa's slower, bigger laugh in the greeting). Not cached here."""
        text = assert_speakable(line)
        samples, sr = self.k.create(text, voice=self._style, speed=speed, lang="en-us")
        assert sr == SR, sr
        return np.asarray(samples, dtype=np.float32)

    def synth(self, line: Spoken) -> np.ndarray:
        text = assert_speakable(line)
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]
        samples, sr = self.k.create(text, voice=self._style, speed=self.speed, lang="en-us")
        assert sr == SR, sr
        samples = np.asarray(samples, dtype=np.float32)
        if len(text.split()) <= 4:
            self._cache[text] = samples
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
        return samples


class PocketTTS:
    """Kyutai Pocket TTS (pocket-tts 4.0.1, CPU, built-in voices only; no voice cloning). The default (SANTA_TTS=pocket).

    Pocket samples randomly, so every line is a fresh take. There is no short-line cache here, so "Ho ho ho!" does
    not repeat the same take. The canned lines are still rendered once (canned.py).
    """
    sr = SR

    def __init__(self, settings):
        import os
        # The library first tries the gated voice-cloning weights and falls back to the ungated ones when that fails.
        # Offline mode makes the first try fail locally instead of contacting Hugging Face.
        if os.environ.get("HF_HUB_OFFLINE") != "1":
            raise RuntimeError("Pocket TTS needs HF_HUB_OFFLINE=1 (nothing may leave the Mac at runtime)")
        from pocket_tts import TTSModel
        self.model = TTSModel.load_model()
        assert self.model.sample_rate == SR, self.model.sample_rate
        self.voice, self.speed = settings.voice, None      # Pocket has no speed setting
        self.state = self.model.get_state_for_audio_prompt(settings.voice)

    def synth(self, line: Spoken) -> np.ndarray:
        text = assert_speakable(line)
        return self.model.generate_audio(self.state, text).numpy().astype(np.float32).reshape(-1)
