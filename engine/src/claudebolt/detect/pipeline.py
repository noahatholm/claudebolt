"""Silence detection: audio -> activity mask -> timeline segments."""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

from ..config import DetectionSettings
from ..media.decode import Analysis, decode
from ..timeline import refine
from ..timeline.model import Project, Segment
from . import multitrack, rms, threshold


def analyses(p: Project, on_progress: Callable[[float], None] | None = None,
             cancel: threading.Event | None = None) -> list[Analysis]:
    out = []
    n = max(1, len(p.tracks))
    for i, t in enumerate(p.tracks):
        out.append(decode(p.source(t.source_id), t.audio_stream,
                          (lambda f, i=i: on_progress((i + f) / n)) if on_progress else None, cancel))
    return out


def resolve_threshold(cfg: DetectionSettings, an: list[Analysis]) -> float:
    if cfg.threshold == "auto":
        return threshold.auto_threshold(an[0].levels)
    return float(cfg.threshold)


def activity(p: Project, cfg: DetectionSettings, an: list[Analysis]) -> tuple[np.ndarray, float]:
    n = len(an[0].levels)
    thr = resolve_threshold(cfg, an)
    masks = []
    for a in an:
        m = rms.active_rms(a.levels, thr)
        if cfg.mode in ("vad", "both"):
            from . import vad

            v = vad.active_vad(a.pcm(), len(a.levels))
            m = v if cfg.mode == "vad" else (m & v)
        masks.append(m)
    mask = multitrack.combine(masks, [t.offset for t in p.tracks], n, cfg.combine)
    return mask, thr


def detect(p: Project, cfg: DetectionSettings | None = None,
           on_progress: Callable[[float], None] | None = None,
           cancel: threading.Event | None = None) -> tuple[list[Segment], float]:
    """Return (segments, threshold used). Does not mutate the project."""
    cfg = cfg or p.detection
    an = analyses(p, on_progress, cancel)
    mask, thr = activity(p, cfg, an)
    pcm = an[0].pcm() if cfg.snap_window > 0 else None
    segs = refine.refine(mask, p.duration, cfg, pcm)
    return segs, thr
