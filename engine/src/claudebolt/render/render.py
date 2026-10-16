"""Run a render: single pass or split-concat for long timelines."""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from ..media import ffmpeg
from ..timeline.model import Project, Segment
from . import encoders
from .graph import Graph, build_graph, pieces

CHUNK_PIECES = 100
SPLIT_PIECES = 300
SPLIT_SECONDS = 2 * 3600


def _codec_args(p: Project, ext: str, has_video: bool, fast: bool) -> list[str]:
    rs = p.render
    if has_video:
        enc = "libx264" if fast else encoders.pick_video_encoder(rs.encoder_pref)
        args = encoders.video_args(enc, rs, fast)
        a = rs.acodec
        args += ["-c:a", a] if a else ["-c:a", "aac", "-b:a", "64k" if fast else "192k"]
        if ext in ("mp4", "m4v", "mov"):
            args += ["-movflags", "+faststart"]
        return args
    bits = p.primary.audio[0].bits if p.primary.audio else None
    return encoders.audio_args(ext, bits, fast)


def _run_graph(p: Project, g: Graph, out: Path, ext: str, fast: bool, total: float,
               on_progress: Callable[[float], None] | None, cancel: threading.Event | None,
               codec: list[str] | None = None) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(g.script)
        script = f.name
    try:
        args: list[str] = []
        for path, off in g.inputs:
            if off:
                args += ["-itsoffset", f"{off:.6f}"]
            args += ["-i", path]
        args += [ffmpeg.filter_script_flag(), script]
        for m in g.maps:
            args += ["-map", m]
        args += codec if codec is not None else _codec_args(p, ext, g.has_video, fast)
        args += [str(out)]
        ffmpeg.run(args, total=total, on_progress=on_progress, cancel=cancel)
    finally:
        Path(script).unlink(missing_ok=True)


def output_ext(p: Project, out: Path) -> str:
    return out.suffix.lower().lstrip(".")


def render(
    p: Project,
    out_path: str | Path,
    *,
    segments: list[Segment] | None = None,
    preview: bool = False,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> dict:
    """Render the edited timeline. Returns {path, expected_duration}."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ext = output_ext(p, out)
    want_video = p.primary.video is not None and ext not in encoders.AUDIO_EXTS
    pcs = pieces(p, segments)
    long_job = len(pcs) > SPLIT_PIECES or p.duration > SPLIT_SECONDS
    split = p.render.split_concat if p.render.split_concat is not None else long_job
    tmp = out.with_name(out.stem + ".part" + out.suffix)  # atomic: never leave a half file at `out`
    try:
        if split and len(pcs) > CHUNK_PIECES:
            exp = _render_split(p, tmp, ext, want_video, pcs, preview, on_progress, cancel)
        else:
            g = build_graph(p, video=want_video, segs=segments,
                            scale_height=540 if preview else None)
            exp = g.duration
            _run_graph(p, g, tmp, ext, preview, exp, on_progress, cancel)
        tmp.replace(out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return {"path": str(out), "expected_duration": exp}


def _render_split(p, tmp: Path, ext: str, want_video: bool, pcs: list[Segment], preview: bool,
                  on_progress, cancel) -> float:
    chunks = [pcs[i:i + CHUNK_PIECES] for i in range(0, len(pcs), CHUNK_PIECES)]
    work = Path(tempfile.mkdtemp(prefix="cbolt_"))
    parts: list[Path] = []
    total = 0.0
    try:
        graphs = [build_graph(p, video=want_video, segs=c, scale_height=540 if preview else None)
                  for c in chunks]
        total = sum(g.duration for g in graphs)
        done = 0.0
        # video chunks reuse the final codec; audio chunks go lossless, then one final encode
        for i, g in enumerate(graphs):
            part = work / f"part{i:04d}.{'mkv' if want_video else 'wav'}"
            base = done

            def prog(f: float, g=g, base=base) -> None:
                if on_progress:
                    on_progress((base + f * g.duration) / total * (0.9 if not want_video else 1.0))

            codec = None if want_video else ["-c:a", "pcm_f32le"]
            _run_graph(p, g, part, "mkv" if want_video else "wav", preview, g.duration, prog,
                       cancel, codec=_codec_args(p, "mkv", True, preview) if want_video else codec)
            parts.append(part)
            done += g.duration
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{x.as_posix()}'\n" for x in parts), "utf-8")
        args = ["-f", "concat", "-safe", "0", "-i", str(lst)]
        if want_video:
            args += ["-c", "copy"]
            if ext in ("mp4", "m4v", "mov"):
                args += ["-movflags", "+faststart"]
        else:
            args += _codec_args(p, ext, False, preview)
        args += ["-f", {"m4v": "mp4"}.get(ext, ext if ext not in ("m4a",) else "ipod"), str(tmp)]
        ffmpeg.run(args, total=total, cancel=cancel)
        return total
    finally:
        for x in work.glob("*"):
            x.unlink(missing_ok=True)
        work.rmdir()


def clip_segments(p: Project, start: float, end: float) -> list[Segment]:
    """Timeline segments restricted to a source-time window (for previews)."""
    out = []
    for s in p.segments:
        a, b = max(s.start, start), min(s.end, end)
        if b - a > 1e-6:
            out.append(s.model_copy(update={"start": a, "end": b}))
    return out
