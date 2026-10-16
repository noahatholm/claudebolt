"""Silero VAD (ONNX) speech probabilities, resampled to the 40 ms grid.

The model file (~2 MB) is looked up in the models dir (`silero_vad.onnx`) or via
CLAUDEBOLT_VAD_MODEL. It is not downloaded implicitly; `ensure_model()` fetches it on request.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import numpy as np

from ..config import models_dir

MODEL_URL = "https://github.com/snakers4/silero-vad/raw/v5.1/src/silero_vad/data/silero_vad.onnx"
FRAME = 512
CONTEXT = 64


class VadUnavailable(RuntimeError):
    pass


def model_path() -> Path:
    return Path(os.environ.get("CLAUDEBOLT_VAD_MODEL") or models_dir() / "silero_vad.onnx")


def ensure_model() -> Path:
    p = model_path()
    if not p.exists():
        tmp = p.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.replace(p)
    return p


def speech_probs(pcm: np.ndarray, rate: int = 16000) -> np.ndarray:
    """Per-512-sample-frame speech probability."""
    try:
        import onnxruntime as ort
    except ImportError as e:  # pragma: no cover
        raise VadUnavailable("onnxruntime not installed: uv sync --extra vad") from e
    p = model_path()
    if not p.exists():
        raise VadUnavailable("VAD model missing: run `claudebolt models vad` to download it")
    sess = ort.InferenceSession(str(p), providers=["CPUExecutionProvider"])
    state = np.zeros((2, 1, 128), dtype=np.float32)
    context = np.zeros((1, CONTEXT), dtype=np.float32)
    sr = np.array(rate, dtype=np.int64)
    n = len(pcm) // FRAME
    out = np.empty(n, dtype=np.float32)
    for i in range(n):
        x = np.asarray(pcm[i * FRAME:(i + 1) * FRAME], dtype=np.float32)[None, :]
        inp = np.concatenate((context, x), axis=1)
        prob, state = sess.run(None, {"input": inp, "state": state, "sr": sr})
        context = inp[:, -CONTEXT:]
        out[i] = float(prob[0][0])
    return out


def active_vad(pcm: np.ndarray, n_windows: int, rate: int = 16000, thresh: float = 0.5) -> np.ndarray:
    """Boolean mask on the 40 ms grid."""
    probs = speech_probs(pcm, rate)
    frame_t = FRAME / rate
    mask = np.zeros(n_windows, dtype=bool)
    for k in range(n_windows):
        a = int(k * 0.04 / frame_t)
        b = max(a + 1, int((k + 1) * 0.04 / frame_t))
        seg = probs[a:b]
        mask[k] = bool(seg.size and seg.max() >= thresh)
    return mask
