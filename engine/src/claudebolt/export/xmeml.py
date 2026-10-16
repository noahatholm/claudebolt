"""Final Cut Pro 7 XML (xmeml v5), importable by Premiere and DaVinci Resolve."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import escape

from ..timeline.model import Project
from .common import clips, timebase


def _rate(fps: Fraction) -> str:
    ntsc = fps.denominator != 1
    tb = round(float(fps))
    return f"<rate><timebase>{tb}</timebase><ntsc>{'TRUE' if ntsc else 'FALSE'}</ntsc></rate>"


def render(p: Project, keep_all_cuts: bool = False) -> str:
    src = p.primary
    video = src.video is not None
    fps = timebase(p)
    rate = _rate(fps)
    name = escape(Path(src.path).stem)
    uri = escape(Path(src.path).resolve().as_uri())
    items = clips(p, keep_all_cuts)
    total = items[-1][4] if items else 0
    nframes = round(src.duration * float(fps))
    channels = src.audio[0].channels if src.audio else 2
    arate = src.audio[0].rate if src.audio else 48000

    file_full = (
        f'<file id="file-1"><name>{name}</name><pathurl>{uri}</pathurl>{rate}'
        f"<duration>{nframes}</duration><media>"
        + (f"<video><samplecharacteristics>{rate}<width>{src.video.width}</width>"
           f"<height>{src.video.height}</height></samplecharacteristics></video>" if video else "")
        + f"<audio><samplecharacteristics><depth>16</depth><samplerate>{arate}</samplerate>"
        f"</samplecharacteristics><channelcount>{channels}</channelcount></audio></media></file>"
    )

    def clipitem(idx: int, seg, a: int, b: int, ra: int, rb: int, kind: str, ch: int = 1) -> str:
        first = idx == 0 and kind == ("video" if video else "audio") and ch == 1
        f = file_full if first else '<file id="file-1"/>'
        speed = ""
        if seg.op == "speed":
            speed = ("<filter><effect><name>Time Remap</name><effectid>timeremap</effectid>"
                     f"<parameter><parameterid>speed</parameterid><value>{seg.speed * 100:g}</value>"
                     "</parameter></effect></filter>")
        track = f"<sourcetrack><mediatype>audio</mediatype><trackindex>{ch}</trackindex></sourcetrack>" \
            if kind == "audio" else ""
        return (f'<clipitem id="{kind}-{ch}-{idx}"><name>{name}</name>'
                f"<enabled>{'FALSE' if seg.op == 'remove' else 'TRUE'}</enabled>"
                f"<duration>{nframes}</duration>{rate}<start>{ra}</start><end>{rb}</end>"
                f"<in>{a}</in><out>{b}</out>{f}{track}{speed}</clipitem>")

    vtrack = ""
    if video:
        vtrack = "<video><track>" + "".join(
            clipitem(i, *c, "video") for i, c in enumerate(items)) + "</track></video>"
    atracks = "".join(
        "<track>" + "".join(clipitem(i, *c, "audio", ch) for i, c in enumerate(items)) + "</track>"
        for ch in range(1, channels + 1))
    vfmt = (f"<video><format><samplecharacteristics>{rate}<width>{src.video.width}</width>"
            f"<height>{src.video.height}</height></samplecharacteristics></format>" if video else "")
    _ = vfmt
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="5">\n'
        f"<sequence><name>{name} (claudebolt)</name><duration>{total}</duration>{rate}"
        f"<media>{vtrack}<audio>{atracks}</audio></media></sequence>\n</xmeml>\n"
    )
