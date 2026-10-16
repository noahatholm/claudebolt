"""Shared helpers for exporters."""

from __future__ import annotations

from fractions import Fraction

from ..timeline.model import Project, Segment


def timebase(p: Project) -> Fraction:
    """Frames per second as an exact fraction (30 for audio-only sources)."""
    v = p.primary.video
    if not v:
        return Fraction(30)
    try:
        a, b = v.fps_rational.split("/")
        f = Fraction(int(a), int(b))
        if f > 0:
            return f
    except Exception:
        pass
    return Fraction(v.fps).limit_denominator(1001)


def to_frames(t: float, fps: Fraction) -> int:
    return round(Fraction(t).limit_denominator(100000) * fps)


def clips(p: Project, keep_all_cuts: bool) -> list[tuple[Segment, int, int, int, int]]:
    """(segment, src_in, src_out, rec_in, rec_out) in frames; removed clips only when kept."""
    fps = timebase(p)
    out = []
    rec = 0
    for s in p.segments:
        if s.op == "remove" and not keep_all_cuts:
            continue
        a, b = to_frames(s.start, fps), to_frames(s.end, fps)
        if b <= a:
            continue
        n = b - a
        rn = max(1, round(n / (s.speed if s.op == "speed" else 1.0)))
        out.append((s, a, b, rec, rec + rn))
        rec += rn
    return out


def tc(frames: int, base: int) -> str:
    f = frames % base
    sec = frames // base
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}:{f:02d}"
