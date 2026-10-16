"""ffprobe -> Source."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from ..timeline.model import AudioStream, Source, VideoInfo
from .ffmpeg import _NOWIN, FFmpegError, ffprobe_path


def _fps(s: str) -> float:
    try:
        a, b = s.split("/")
        return float(a) / float(b) if float(b) else 0.0
    except Exception:
        return 0.0


def fast_sha256(path: Path) -> str:
    """sha256 over size + first/last 16 MB (fast on huge files)."""
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(16 << 20))
        if size > 32 << 20:
            f.seek(size - (16 << 20))
            h.update(f.read(16 << 20))
    return h.hexdigest()


def probe(path: str | Path, source_id: str = "s0") -> Source:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    out = subprocess.run(
        [ffprobe_path(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)],
        capture_output=True, text=True, creationflags=_NOWIN,
    )
    if out.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {out.stderr.strip()}")
    info = json.loads(out.stdout)
    streams = info.get("streams", [])
    audio = [
        AudioStream(
            index=i, channels=int(s.get("channels", 1)), rate=int(s.get("sample_rate", 0) or 0),
            codec=s.get("codec_name", ""), lang=(s.get("tags") or {}).get("language"),
            bits=int(s.get("bits_per_sample") or s.get("bits_per_raw_sample") or 0) or None,
        )
        for i, s in enumerate(x for x in streams if x.get("codec_type") == "audio")
    ]
    vids = [s for s in streams if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")]
    video = None
    if vids:
        v = vids[0]
        fps = _fps(v.get("avg_frame_rate", "0/1")) or _fps(v.get("r_frame_rate", "0/1")) or 30.0
        rfps = _fps(v.get("r_frame_rate", "0/1"))
        video = VideoInfo(
            width=int(v["width"]), height=int(v["height"]), fps=fps, codec=v.get("codec_name", ""),
            vfr=bool(rfps and abs(rfps - fps) > 0.01 * max(fps, 1)),
            fps_rational=v.get("r_frame_rate", "30/1"),
        )
    if not audio:
        raise FFmpegError(f"{path.name} has no audio stream")
    dur = float(info.get("format", {}).get("duration") or 0)
    if not dur:
        dur = max(float(s.get("duration") or 0) for s in streams)
    return Source(
        id=source_id, path=str(path.resolve()), kind="video" if video else "audio",
        duration=dur, sha256=fast_sha256(path), video=video, audio=audio,
        format=path.suffix.lower().lstrip("."),
    )
