"""Exporters: fcpxml, xmeml, edl, srt, vtt, audacity labels, cutlist JSON."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..timeline.model import Project, output_to_source, source_to_output
from . import captions, edl, fcpxml, xmeml

FORMATS = ["fcpxml", "xmeml", "edl", "srt", "vtt", "audacity", "cutlist"]
EXT = {"fcpxml": ".fcpxml", "xmeml": ".xml", "edl": ".edl", "srt": ".srt", "vtt": ".vtt",
       "audacity": ".txt", "cutlist": ".json"}


def audacity(p: Project) -> str:
    return "".join(f"{s.start:.6f}\t{s.end:.6f}\t{s.reason or 'removed'}\n"
                   for s in p.segments if s.op == "remove")


def cutlist(p: Project) -> str:
    segs = []
    for s in p.segments:
        d = s.model_dump()
        d["out_start"] = source_to_output(p.segments, s.start)
        d["out_end"] = source_to_output(p.segments, s.end)
        segs.append(d)
    return json.dumps({
        "source": p.primary.path, "duration": p.duration, "output_duration": p.output_duration,
        "segments": segs, "proposals": [x.model_dump() for x in p.proposals]}, indent=2)


def export(p: Project, fmt: str, path: str | Path, keep_all_cuts: bool = False) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}")
    if fmt == "fcpxml":
        text = fcpxml.render(p, keep_all_cuts)
    elif fmt == "xmeml":
        text = xmeml.render(p, keep_all_cuts)
    elif fmt == "edl":
        text = edl.render(p, keep_all_cuts)
    elif fmt == "srt":
        text = captions.srt(p)
    elif fmt == "vtt":
        text = captions.vtt(p)
    elif fmt == "audacity":
        text = audacity(p)
    else:
        text = cutlist(p)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, out)
    return str(out)


__all__ = ["EXT", "FORMATS", "export", "output_to_source", "source_to_output"]
