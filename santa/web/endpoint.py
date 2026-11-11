"""End-of-speech detection on VAD-gated frames (sections 4.2, 4.3, 4.6). Pure logic: frames, probabilities and
times go in, events come out. No audio leaves this object except as an Utterance for STT.

Rules:
  - speech starts at a frame with probability >= vad_on and continues while >= vad_off;
  - a rolling pre-roll (preroll_ms) is kept while nobody speaks, and put in front of the utterance;
  - the turn ends after eos_ms of silence. If the turn has less than eos_short_speech_ms of speech when that wait is
    reached, the wait is extended ONCE (per turn) to eos_extend_ms;
  - a turn whose speech is shorter than min_speech_ms is dropped (never sent to STT);
  - a turn longer than max_utterance_s is ended at once.
"""
import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from .audio import FRAME_MS


@dataclass
class Utterance:
    audio: np.ndarray
    speech_ms: float      # voiced frames only
    t_first: float        # first voiced frame
    t_last: float         # end of the last voiced frame
    t_end: float          # the endpoint decision
    eos_wait_ms: float    # the wait that ended the turn
    extended: bool        # the extend-once rule fired in this turn
    forced: bool = False  # max_utterance_s reached


@dataclass
class Dropped:
    speech_ms: float
    extended: bool


class Endpointer:
    def __init__(self, s):
        self.s = s
        self.preroll_frames = max(1, math.ceil(s.preroll_ms / FRAME_MS))
        self.tail_frames = max(0, math.ceil(s.tail_ms / FRAME_MS))
        self.extend_fired = 0         # how often the extend-once rule fired (logged)
        self.turns = 0
        self.reset()

    def reset(self) -> None:
        """Call whenever the mic (re)opens: nothing heard before this moment is kept."""
        self.preroll: deque = deque(maxlen=self.preroll_frames)
        self.in_speech = False
        self.frames: list[np.ndarray] = []
        self.voiced_ms = 0.0
        self.silence_ms = 0.0
        self.wait_ms = self.s.eos_ms
        self.extended = False
        self.t_first = self.t_last = 0.0
        self.last_voiced_index = 0
        self.start_index = 0

    def push(self, frame: np.ndarray, prob: float, now: float):
        """now = arrival time of the END of this frame. Returns None, "start", an Utterance or a Dropped."""
        if not self.in_speech:
            if prob >= self.s.vad_on:
                self.in_speech = True
                self.frames = list(self.preroll) + [frame]
                self.start_index = len(self.preroll)
                self.preroll.clear()
                self.voiced_ms = FRAME_MS
                self.silence_ms = 0.0
                self.wait_ms = self.s.eos_ms
                self.extended = False
                self.t_first = self.t_last = now
                self.last_voiced_index = len(self.frames) - 1
                return "start"
            self.preroll.append(frame)
            return None

        self.frames.append(frame)
        if prob >= self.s.vad_off:
            self.voiced_ms += FRAME_MS
            self.silence_ms = 0.0
            self.t_last = now
            self.last_voiced_index = len(self.frames) - 1
            if self.extended:
                self.wait_ms = self.s.eos_ms   # speech came back: the normal wait again (the rule stays used up)
        else:
            self.silence_ms += FRAME_MS
        if (len(self.frames) - self.start_index) * FRAME_MS >= self.s.max_utterance_s * 1000:
            return self._finish(now, forced=True)
        if self.silence_ms >= self.wait_ms:
            if (self.s.eos_extend and not self.extended and self.voiced_ms < self.s.eos_short_speech_ms
                    and self.s.eos_extend_ms > self.wait_ms):
                self.extended = True
                self.wait_ms = self.s.eos_extend_ms
                self.extend_fired += 1
                return None
            return self._finish(now)
        return None

    def _finish(self, now: float, forced: bool = False):
        keep = self.frames[:self.last_voiced_index + 1 + self.tail_frames]
        speech_ms, extended, wait = self.voiced_ms, self.extended, self.wait_ms
        t_first, t_last = self.t_first, self.t_last
        self.reset()
        self.turns += 1
        if speech_ms < self.s.min_speech_ms:
            return Dropped(speech_ms=speech_ms, extended=extended)
        return Utterance(audio=np.concatenate(keep), speech_ms=speech_ms, t_first=t_first, t_last=t_last, t_end=now,
                         eos_wait_ms=wait, extended=extended, forced=forced)
