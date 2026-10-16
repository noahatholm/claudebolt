"""CMX3600 EDL: one event per kept segment (speed changes use M2 motion lines)."""

from __future__ import annotations

from pathlib import Path

from ..timeline.model import Project
from .common import clips, tc, timebase


def render(p: Project, keep_all_cuts: bool = False) -> str:
    fps = timebase(p)
    base = round(float(fps))
    name = Path(p.primary.path).stem
    track = "AA/V" if p.primary.video else "AA"
    lines = [f"TITLE: {name}", "FCM: NON-DROP FRAME", ""]
    n = 0
    for seg, a, b, ra, rb in clips(p, keep_all_cuts=False):
        n += 1
        lines.append(f"{n:03d}  AX       {track:<5} C        {tc(a, base)} {tc(b, base)} "
                     f"{tc(ra, base)} {tc(rb, base)}")
        if seg.op == "speed":
            lines.append(f"M2   AX       {float(fps) * seg.speed:05.1f}                {tc(a, base)}")
        lines.append(f"* FROM CLIP NAME: {Path(p.primary.path).name}")
    if keep_all_cuts:
        lines.append("")
        for seg, a, b, *_ in clips(p, keep_all_cuts=True):
            if seg.op == "remove":
                lines.append(f"* REMOVED ({seg.reason}) {tc(a, base)} - {tc(b, base)}")
    return "\n".join(lines) + "\n"
