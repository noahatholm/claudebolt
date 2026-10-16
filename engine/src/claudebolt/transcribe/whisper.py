"""faster-whisper transcription in overlapping windows, cached by audio hash + model."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

import numpy as np

from ..media.decode import RATE, Analysis, stream_dir
from ..media.ffmpeg import Cancelled
from ..timeline.model import Source, Transcript, Word
from . import models
from .sentences import build

WINDOW = 600.0
OVERLAP = 2.0
PROMPT = "Um, uh, so, like, you know, I mean, uh, hmm."


def cache_path(src: Source, stream: int, model: str):
    return stream_dir(src, stream) / f"transcript.{model}.json"


def load_cached(src: Source, stream: int, model: str) -> Transcript | None:
    p = cache_path(src, stream, model)
    if p.exists():
        try:
            return Transcript.model_validate_json(p.read_text("utf-8"))
        except Exception:
            return None
    return None


def _device() -> tuple[str, str]:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def transcribe(
    src: Source,
    stream: int,
    an: Analysis,
    model: str = "small.en",
    language: str | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> Transcript:
    cached = load_cached(src, stream, model)
    if cached is not None:
        if on_progress:
            on_progress(1.0)
        return cached
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise models.ModelError("faster-whisper not installed: uv sync --extra whisper") from e
    if not models.installed(model):
        raise models.ModelError(f"model {model!r} not downloaded; call download_model first")
    device, ctype = _device()
    wm = WhisperModel(str(models.model_dir(model)), device=device, compute_type=ctype,
                      cpu_threads=max(1, (os.cpu_count() or 2) // 2))
    pcm = an.pcm()
    total = len(pcm) / RATE
    lang = language or ("en" if model.endswith(".en") else None)
    words: list[Word] = []
    k = 0
    detected = lang or "en"
    while k * WINDOW < total:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        t0 = max(0.0, k * WINDOW - (OVERLAP if k else 0.0))
        t1 = min(total, (k + 1) * WINDOW)
        chunk = np.asarray(pcm[int(t0 * RATE):int(t1 * RATE)], dtype=np.float32)
        segs, info = wm.transcribe(chunk, language=lang, word_timestamps=True, vad_filter=True,
                                   condition_on_previous_text=False, initial_prompt=PROMPT)
        detected = info.language or detected
        lo, hi = k * WINDOW, (k + 1) * WINDOW
        for s in segs:
            for w in s.words or []:
                a, b = w.start + t0, w.end + t0
                mid = (a + b) / 2
                if (k == 0 or mid >= lo) and (mid < hi or t1 >= total):
                    words.append(Word(text=w.word, start=round(a, 3), end=round(b, 3),
                                      prob=round(float(w.probability), 3)))
        k += 1
        if on_progress:
            on_progress(min(1.0, t1 / total))
    tr = build(words, model, detected)
    p = cache_path(src, stream, model)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(tr.model_dump_json(), "utf-8")
    tmp.replace(p)
    return tr
