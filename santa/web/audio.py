"""Audio plumbing: 16 kHz mono int16 in from the browser, 24 kHz int16 out to it. Nothing is written to disk here."""
import struct

import numpy as np

SR_IN = 16000
FRAME = 512                     # Silero VAD frame at 16 kHz (32 ms)
FRAME_MS = FRAME * 1000 / SR_IN
SR_OUT = 24000                  # Kokoro
OUT_CHUNK = 4800                # 200 ms per WebSocket message


class FrameBuffer:
    """Bytes of int16 PCM in any sizes -> float32 frames of exactly FRAME samples."""

    def __init__(self):
        self.buf = np.zeros(0, dtype=np.float32)

    def clear(self) -> None:
        self.buf = np.zeros(0, dtype=np.float32)

    def push(self, data: bytes) -> list[np.ndarray]:
        if len(data) % 2:
            data = data[:-1]
        x = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        self.buf = np.concatenate([self.buf, x])
        n = len(self.buf) // FRAME
        frames = [self.buf[i * FRAME:(i + 1) * FRAME] for i in range(n)]
        self.buf = self.buf[n * FRAME:]
        return frames


def to_int16_bytes(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def out_messages(uid: int, samples: np.ndarray) -> list[bytes]:
    """Binary messages for one synthesized sentence: 4-byte little-endian utterance id + int16 PCM at SR_OUT."""
    head = struct.pack("<I", uid)
    return [head + to_int16_bytes(samples[i:i + OUT_CHUNK]) for i in range(0, len(samples), OUT_CHUNK)]


def write_debug_wav(path, samples: np.ndarray, sr: int = SR_IN) -> None:
    """Only called with --debug-audio."""
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(to_int16_bytes(samples))
