"""Auto threshold + audio analysis summary."""

from __future__ import annotations

import numpy as np

from .rms import histogram


def auto_threshold(levels: np.ndarray) -> float:
    lv = np.asarray(levels)
    live = lv[lv > -90]
    if not live.size:
        return -35.0
    floor = float(np.percentile(live, 15))
    return float(np.clip(floor + 6.0, -60.0, -20.0))


def analyze(levels: np.ndarray) -> dict:
    lv = np.asarray(levels)
    live = lv[lv > -90]
    if not live.size:
        return {"suggested_threshold": -35.0, "floor_db": None, "speech_db": None,
                "histogram": histogram(lv), "warnings": ["audio is silent"]}
    floor = float(np.percentile(live, 15))
    speech = float(np.percentile(live, 85))
    warnings = []
    if speech - floor < 10:
        warnings.append("low dynamic range - consider VAD mode")
    return {
        "suggested_threshold": auto_threshold(lv),
        "floor_db": round(floor, 1),
        "speech_db": round(speech, 1),
        "histogram": histogram(lv),
        "warnings": warnings,
    }
