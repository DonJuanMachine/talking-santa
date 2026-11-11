"""Synthetic speech for Stage H (macOS `say`, adult voices, NOT child speech).

    clips() -> list of dicts {id, text, voice, path, seconds}; WAVs are 16 kHz mono int16 in CACHE (outside the repo).

The clips are only stand-ins for timing and for a rough accuracy check. They say nothing about how well a
recognizer understands a 4-year-old.
"""
import subprocess
import wave
from pathlib import Path

import numpy as np

CACHE = Path.home() / ".cache" / "talking-santa" / "synth"
SR = 16000

# (id, text). Durations are approximate (2 s / 5 s / 10 s buckets for the STT benchmark).
PHRASES = [
    ("s2_hi_emma", "Hi Santa! I'm Emma!"),
    ("s2_puppy", "I want a puppy please."),
    ("s2_max", "This is Ziv. Hello!"),
    ("s5_leo_truck", "My name is Leo and I want a big red truck and a dinosaur for Christmas."),
    ("s5_cat", "I have a cat called Mittens and she sleeps on my bed every night."),
    ("s5_snow", "Do the reindeer like snow? We made a snowman in the garden today."),
    ("s10_story", "Santa, guess what, today we went to the park and I went down the big slide, and then my "
                  "brother fell over, but he was okay, and then we had ice cream with sprinkles on top."),
    ("s10_list", "For Christmas I would like a teddy bear, a puzzle with lots of animals, some crayons, a "
                 "blue scooter, and a book about space and rockets and the moon and the stars."),
    ("t_thanks", "Thank you, Santa!"),
    ("t_hamster", "I have a hamster named Nibbles."),
    ("t_what_cat", "What is my cat called?"),
    ("t_cookies", "Do you like cookies?"),
    ("t_elves", "How many elves do you have?"),
    ("t_sled", "Can I ride on your sleigh?"),
    ("t_bye", "Bye bye Santa!"),
]
VOICES = ["Samantha", "Daniel", "Karen"]


def _say(text: str, voice: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.wav")
    subprocess.run(["say", "-v", voice, "-o", str(tmp), "--file-format=WAVE", f"--data-format=LEI16@{SR}", text],
                   check=True)
    tmp.replace(path)


def read_wav(path) -> np.ndarray:
    """float32 mono in [-1, 1] at the file's rate (expects 16 kHz int16 mono)."""
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, path
        assert w.getframerate() == SR, (path, w.getframerate())
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


def clips(voices=VOICES, phrases=PHRASES) -> list[dict]:
    out = []
    for voice in voices:
        for pid, text in phrases:
            p = CACHE / f"{pid}__{voice}.wav"
            if not p.exists():
                _say(text, voice, p)
            out.append({"id": pid, "text": text, "voice": voice, "path": p, "seconds": len(read_wav(p)) / SR})
    return out


if __name__ == "__main__":
    for c in clips():
        print(f"{c['seconds']:5.1f}s  {c['voice']:9s} {c['id']}")
