"""Activity masks from per-window levels."""

from __future__ import annotations

import numpy as np


def active_rms(levels: np.ndarray, threshold: float) -> np.ndarray:
    return np.asarray(levels) >= threshold


def histogram(levels: np.ndarray, bins: int = 20) -> dict:
    lv = np.asarray(levels)
    lv = lv[lv > -90]
    if not lv.size:
        return {"edges": [], "counts": []}
    counts, edges = np.histogram(lv, bins=bins, range=(-90, 0))
    return {"edges": edges.round(1).tolist(), "counts": counts.tolist()}
