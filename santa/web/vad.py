"""Silero VAD (v5 ONNX) without torch: one probability per 512-sample frame at 16 kHz."""
import numpy as np

from .audio import FRAME, SR_IN

CONTEXT = 64   # the v5 model expects the last 64 samples of the previous frame in front of each frame


class SileroVAD:
    def __init__(self, path):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self._sr = np.array(SR_IN, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, CONTEXT), dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        assert len(frame) == FRAME
        x = np.concatenate([self.context, frame.reshape(1, -1).astype(np.float32)], axis=1)
        out, self.state = self.sess.run(None, {"input": x, "state": self.state, "sr": self._sr})
        self.context = x[:, -CONTEXT:]
        return float(out[0][0])
