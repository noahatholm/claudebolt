"""Pure interval functions turning an activity mask into keep/remove segments."""

from __future__ import annotations

import numpy as np

from ..config import DetectionSettings
from .model import Segment

Interval = tuple[float, float]
WINDOW = 0.04


def runs(active: np.ndarray, window: float = WINDOW) -> list[Interval]:
    """Contiguous True windows -> [(start, end)] seconds."""
    a = np.asarray(active, dtype=bool)
    if not a.size:
        return []
    d = np.diff(np.concatenate(([0], a.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(float(s * window), float(e * window)) for s, e in zip(starts, ends)]


def grace(iv: list[Interval], g: float) -> list[Interval]:
    """Fill gaps between keeps that are <= g seconds."""
    out: list[Interval] = []
    for s, e in iv:
        if out and s - out[-1][1] <= g + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def pad(iv: list[Interval], left: float, right: float, duration: float) -> list[Interval]:
    return [(max(0.0, s - left), min(duration, e + right)) for s, e in iv]


def merge(iv: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def min_keep(iv: list[Interval], m: float) -> list[Interval]:
    return [(s, e) for s, e in iv if e - s >= m - 1e-9]


def snap(iv: list[Interval], pcm: np.ndarray | None, rate: int, window: float,
         duration: float) -> list[Interval]:
    """Move each boundary to the lowest-energy 1 ms frame within +-window."""
    if pcm is None or window <= 0 or not len(pcm):
        return iv
    frame = max(1, rate // 1000)

    def best(t: float, lo_lim: float, hi_lim: float) -> float:
        lo = max(lo_lim, t - window)
        hi = min(hi_lim, t + window)
        a, b = int(lo * rate), int(hi * rate)
        n = (b - a) // frame
        if n < 2:
            return t
        seg = np.asarray(pcm[a:a + n * frame], dtype=np.float32).reshape(n, frame)
        e = (seg * seg).mean(axis=1)
        return (a + int(np.argmin(e)) * frame + frame // 2) / rate

    out: list[Interval] = []
    for i, (s, e) in enumerate(iv):
        prev_end = out[-1][1] if out else 0.0
        next_start = iv[i + 1][0] if i + 1 < len(iv) else duration
        s2 = best(s, prev_end, e) if s > 0 else s
        e2 = best(e, s2, next_start) if e < duration else e
        out.append((s2, max(e2, s2)))
    return out


def complete(iv: list[Interval], duration: float, cfg: DetectionSettings) -> list[Segment]:
    """Alternating keep/remove segments tiling [0, duration]."""
    segs: list[Segment] = []
    cur = 0.0
    for s, e in iv:
        if s - cur > 1e-6:
            segs.append(_gap(cur, s, cfg))
        segs.append(Segment(start=s, end=e, op="keep"))
        cur = e
    if duration - cur > 1e-6:
        segs.append(_gap(cur, duration, cfg))
    return segs


def _gap(s: float, e: float, cfg: DetectionSettings) -> Segment:
    if cfg.silence_action == "speed" and cfg.speed_min <= e - s <= cfg.speed_max:
        return Segment(start=s, end=e, op="speed", speed=cfg.speed_rate, reason="silence")
    return Segment(start=s, end=e, op="remove", reason="silence")


def refine(
    active: np.ndarray,
    duration: float,
    cfg: DetectionSettings,
    pcm: np.ndarray | None = None,
    rate: int = 16000,
) -> list[Segment]:
    iv = runs(active)
    iv = grace(iv, cfg.grace)
    iv = pad(iv, cfg.pad_left, cfg.pad_right, duration)
    iv = merge(iv)
    iv = min_keep(iv, cfg.min_keep)
    iv = snap(iv, pcm, rate, cfg.snap_window, duration)
    if cfg.keep_edges and iv:
        iv[0] = (0.0, iv[0][1])
        iv[-1] = (iv[-1][0], duration)
    if not iv:  # nothing survived: keep everything rather than emit an empty file
        return [Segment(start=0.0, end=duration)]
    return complete(iv, duration, cfg)
