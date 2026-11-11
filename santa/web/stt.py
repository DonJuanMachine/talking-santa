"""Speech to text: mlx-whisper (Apple MLX, Metal), in-process. Chosen in H1 (tools/probes/out/h_stt.md).

Every transcript may be wrong. Nothing is filtered by phrase: a transcript is only rejected (-> "say that again")
when it is empty or the recognizer itself reports low confidence.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class Transcript:
    text: str
    ok: bool                       # False -> Santa says the canned "say that again" line
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    why: str | None = None         # "empty" | "low_logprob" | "no_speech" | "repetition"


def name_hint(names: list[str]) -> str:
    """Built at runtime from the registered profiles; "Santa" helps too ("Hi, Sana" in H1)."""
    return "Santa, " + ", ".join(names) + "." if names else "Santa."


def judge(text: str, segs: list[dict], s) -> Transcript:
    text = (text or "").strip()
    avg = min((g.get("avg_logprob", 0.0) for g in segs), default=None)
    nsp = max((g.get("no_speech_prob", 0.0) for g in segs), default=None)
    comp = max((g.get("compression_ratio", 0.0) for g in segs), default=0.0)
    why = None
    if not any(ch.isalnum() for ch in text):
        why = "empty"
    elif avg is not None and avg < s.stt_min_logprob:
        why = "low_logprob"
    elif nsp is not None and nsp > s.stt_max_no_speech:
        why = "no_speech"
    elif comp > s.stt_max_compression:
        why = "repetition"
    return Transcript(text=text, ok=why is None, avg_logprob=avg, no_speech_prob=nsp, why=why)


class MlxWhisperSTT:
    def __init__(self, settings):
        import mlx_whisper  # noqa: F401  (import once, on the STT thread's first call it compiles)
        self.s = settings
        self.repo = settings.stt_repo

    def warm(self) -> None:
        self.transcribe(np.zeros(16000, dtype=np.float32) + 1e-4, [])

    def transcribe(self, audio: np.ndarray, names: list[str]) -> Transcript:
        import mlx_whisper
        r = mlx_whisper.transcribe(audio.astype(np.float32), path_or_hf_repo=self.repo, language="en",
                                   initial_prompt=name_hint(names), temperature=0.0,
                                   condition_on_previous_text=False, verbose=None)
        return judge(r.get("text", ""), r.get("segments", []), self.s)
