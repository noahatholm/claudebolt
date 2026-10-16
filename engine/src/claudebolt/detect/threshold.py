"""Auto threshold + audio analysis summary."""

from __future__ import annotations

import numpy as np

from .rms import histogram

DIGITAL_SILENCE = -90.0


def _floor_speech(levels: np.ndarray) -> tuple[float, float] | None:
    lv = np.asarray(levels, dtype=np.float64)
    live = lv[lv > DIGITAL_SILENCE]
    if not live.size:
        return None
    # Mostly gated/digital silence (synthetic or noise-gated audio): that silence IS the floor.
    pool = np.clip(lv, DIGITAL_SILENCE, None) if live.size < 0.7 * lv.size else live
    return float(np.percentile(pool, 15)), float(np.percentile(live, 85))


def auto_threshold(levels: np.ndarray) -> float:
    fs = _floor_speech(levels)
    if fs is None:
        return -35.0
    return float(np.clip(fs[0] + 6.0, -60.0, -20.0))


def analyze(levels: np.ndarray) -> dict:
    fs = _floor_speech(levels)
    if fs is None:
        return {"suggested_threshold": -35.0, "floor_db": None, "speech_db": None,
                "histogram": histogram(levels), "warnings": ["audio is silent"]}
    floor, speech = fs
    warnings = []
    if speech - floor < 10:
        warnings.append("low dynamic range - consider VAD mode")
    return {
        "suggested_threshold": auto_threshold(levels),
        "floor_db": round(floor, 1),
        "speech_db": round(speech, 1),
        "histogram": histogram(levels),
        "warnings": warnings,
    }
