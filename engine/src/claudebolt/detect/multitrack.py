"""Combine per-track activity masks and estimate sync offsets."""

from __future__ import annotations

import numpy as np

WINDOW = 0.04


def shift_mask(mask: np.ndarray, offset: float, n: int) -> np.ndarray:
    """Place a track's mask on the primary timeline (track time + offset = primary time)."""
    k = int(round(offset / WINDOW))
    out = np.zeros(n, dtype=bool)
    if k >= 0:
        m = mask[: max(0, n - k)]
        out[k:k + len(m)] = m
    else:
        m = mask[-k:][:n]
        out[: len(m)] = m
    return out


def combine(masks: list[np.ndarray], offsets: list[float], n: int, mode: str = "any") -> np.ndarray:
    if not masks:
        return np.zeros(n, dtype=bool)
    if mode == "primary":
        return shift_mask(masks[0], offsets[0], n)
    out = np.zeros(n, dtype=bool)
    for m, o in zip(masks, offsets):
        out |= shift_mask(m, o, n)
    return out


def estimate_offset(ref_pcm: np.ndarray, other_pcm: np.ndarray, rate: int = 16000,
                    seconds: float = 120.0, max_lag: float = 10.0) -> float:
    """Seconds to add to `other` times so they line up with `ref` (envelope cross-correlation, ~1 ms)."""
    dec = 2  # 8 kHz envelopes
    n = int(seconds * rate)

    def env(x: np.ndarray) -> np.ndarray:
        x = np.abs(np.asarray(x[:n], dtype=np.float32))
        k = len(x) // dec * dec
        return x[:k].reshape(-1, dec).mean(axis=1)

    a, b = env(ref_pcm), env(other_pcm)
    a, b = a - a.mean(), b - b.mean()
    size = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    cc = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    sr = rate / dec
    ml = int(max_lag * sr)
    cand = np.concatenate((cc[:ml], cc[-ml:]))
    idx = np.concatenate((np.arange(ml), np.arange(-ml, 0)))
    return float(idx[int(np.argmax(cand))] / sr)
