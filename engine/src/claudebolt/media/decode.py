"""Streaming decode to 16 kHz mono float32, with incremental levels + peaks, cached on disk."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import cache_dir
from ..timeline.model import Source
from .ffmpeg import _NOWIN, Cancelled, FFmpegError, ffmpeg_path

RATE = 16000
WINDOW = 640  # 40 ms at 16 kHz
PEAK_HOP = 160  # 100 peaks / second
CHUNK = RATE * 4  # samples read per iteration (multiple of WINDOW and PEAK_HOP)
VERSION = 2


@dataclass
class Analysis:
    """Decoded audio summary for one (source, audio stream)."""

    levels: np.ndarray  # dBFS per 40 ms window (float32)
    peaks: np.ndarray  # shape (n, 2) min/max per 10 ms (float16)
    pcm_path: Path
    duration: float

    def pcm(self) -> np.ndarray:
        return np.memmap(self.pcm_path, dtype=np.float32, mode="r")


def stream_dir(src: Source, stream: int) -> Path:
    d = cache_dir() / (src.sha256[:32] or "nohash") / f"a{stream}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def decode(
    src: Source,
    stream: int = 0,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> Analysis:
    d = stream_dir(src, stream)
    meta = d / "meta.json"
    pcm_path = d / "pcm16k.f32"
    if meta.exists() and pcm_path.exists():
        m = json.loads(meta.read_text())
        if m.get("v") == VERSION:
            return Analysis(
                levels=np.load(d / "levels.npy"), peaks=np.load(d / "peaks.npy"),
                pcm_path=pcm_path, duration=m["duration"],
            )

    cmd = [ffmpeg_path(), "-nostdin", "-v", "error", "-i", src.path, "-map", f"0:a:{stream}",
           "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_NOWIN)
    assert proc.stdout is not None and proc.stderr is not None
    levels: list[np.ndarray] = []
    peaks: list[np.ndarray] = []
    carry = np.empty(0, dtype=np.float32)
    total = 0
    expect = max(1.0, src.duration * RATE)
    tmp = d / "pcm16k.tmp"
    try:
        with tmp.open("wb") as out:
            while True:
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    raise Cancelled()
                raw = proc.stdout.read(CHUNK * 4)
                if not raw:
                    break
                raw = raw[: len(raw) // 4 * 4]
                x = np.frombuffer(raw, dtype=np.float32)
                out.write(x.tobytes())
                total += len(x)
                buf = np.concatenate((carry, x)) if len(carry) else x
                n = len(buf) // WINDOW * WINDOW  # WINDOW is a multiple of PEAK_HOP
                if n:
                    body = buf[:n]
                    w = body.reshape(-1, WINDOW)
                    levels.append(_db(np.sqrt((w.astype(np.float64) ** 2).mean(axis=1))))
                    p = body.reshape(-1, PEAK_HOP)
                    peaks.append(np.stack((p.min(axis=1), p.max(axis=1)), axis=1))
                carry = buf[n:].copy()
                if on_progress:
                    on_progress(min(1.0, total / expect))
        rc = proc.wait()
        if rc != 0:
            raise FFmpegError(f"decode failed: {proc.stderr.read().decode(errors='replace')[-1500:]}")
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        tmp.unlink(missing_ok=True)
        raise
    if len(carry):  # tail (< one window)
        c = carry.astype(np.float64)
        levels.append(_db(np.array([np.sqrt((c**2).mean())])))
        k = int(np.ceil(len(carry) / PEAK_HOP))
        padded = np.pad(carry, (0, k * PEAK_HOP - len(carry)))
        p = padded.reshape(-1, PEAK_HOP)
        peaks.append(np.stack((p.min(axis=1), p.max(axis=1)), axis=1))
    tmp.replace(pcm_path)
    lv = np.concatenate(levels).astype(np.float32) if levels else np.empty(0, np.float32)
    pk = np.concatenate(peaks).astype(np.float16) if peaks else np.empty((0, 2), np.float16)
    np.save(d / "levels.npy", lv)
    np.save(d / "peaks.npy", pk)
    duration = total / RATE
    meta.write_text(json.dumps({"v": VERSION, "duration": duration}))
    if on_progress:
        on_progress(1.0)
    return Analysis(levels=lv, peaks=pk, pcm_path=pcm_path, duration=duration)


def _db(rms: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(rms + 1e-10)


def resample_peaks(peaks: np.ndarray, buckets: int) -> np.ndarray:
    """Reduce (n,2) min/max peaks to `buckets` (min,max) pairs."""
    n = len(peaks)
    if n == 0 or buckets <= 0:
        return np.zeros((0, 2), np.float32)
    if buckets >= n:
        return peaks.astype(np.float32)
    edges = np.linspace(0, n, buckets + 1).astype(int)
    out = np.empty((buckets, 2), np.float32)
    for i in range(buckets):
        a, b = edges[i], max(edges[i + 1], edges[i] + 1)
        seg = peaks[a:b].astype(np.float32)
        out[i] = (seg[:, 0].min(), seg[:, 1].max())
    return out
