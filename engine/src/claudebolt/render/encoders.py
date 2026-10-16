"""Encoder discovery + codec argument mapping."""

from __future__ import annotations

import functools
import subprocess

from ..config import RenderSettings
from ..media.ffmpeg import _NOWIN, ffmpeg_path

AUDIO_EXTS = {"wav", "mp3", "m4a", "flac", "ogg", "opus", "aac", "aiff", "aif", "wma"}
GPU_ORDER = ["h264_nvenc", "h264_qsv", "h264_amf"]


@functools.lru_cache(maxsize=1)
def available() -> frozenset[str]:
    out = subprocess.run([ffmpeg_path(), "-hide_banner", "-encoders"], capture_output=True,
                         text=True, creationflags=_NOWIN).stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VA":
            names.add(parts[1])
    return frozenset(names)


@functools.lru_cache(maxsize=8)
def verified(enc: str) -> bool:
    """1-frame test encode, so we never trust an encoder the machine can't actually run."""
    if enc not in available():
        return False
    r = subprocess.run(
        [ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1:r=10",
         "-frames:v", "1", "-c:v", enc, "-f", "null", "-"],
        capture_output=True, creationflags=_NOWIN)
    return r.returncode == 0


def pick_video_encoder(pref: str) -> str:
    if pref == "auto":
        for e in GPU_ORDER:
            if verified(e):
                return e
        return "libx264"
    if pref != "libx264" and not verified(pref):
        return "libx264"
    return pref


def video_args(enc: str, rs: RenderSettings, fast: bool = False) -> list[str]:
    if fast:
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p"]
    if enc == "h264_nvenc":
        return ["-c:v", enc, "-preset", "p5", "-cq", str(rs.crf + 1), "-pix_fmt", "yuv420p"]
    if enc in ("h264_qsv", "h264_amf"):
        return ["-c:v", enc, "-global_quality", str(rs.crf), "-pix_fmt", "yuv420p"]
    a = ["-c:v", enc, "-preset", rs.preset, "-pix_fmt", "yuv420p"]
    a += ["-b:v", rs.bitrate] if rs.bitrate else ["-crf", str(rs.crf)]
    return a


def audio_args(ext: str, bits: int | None = None, fast: bool = False) -> list[str]:
    ext = ext.lower().lstrip(".")
    if fast:
        return ["-c:a", "libmp3lame", "-b:a", "64k"] if ext == "mp3" else ["-c:a", "aac", "-b:a", "64k"]
    return {
        "wav": ["-c:a", "pcm_s24le" if bits and bits >= 24 else "pcm_s16le"],
        "aiff": ["-c:a", "pcm_s16be"], "aif": ["-c:a", "pcm_s16be"],
        "flac": ["-c:a", "flac"],
        "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
        "m4a": ["-c:a", "aac", "-b:a", "192k"],
        "aac": ["-c:a", "aac", "-b:a", "192k"],
        "opus": ["-c:a", "libopus", "-b:a", "128k"],
        "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    }.get(ext, ["-c:a", "aac", "-b:a", "192k"])
