"""FCPXML 1.11: asset-clip per kept segment on the spine; speed via timeMap."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import quoteattr

from ..timeline.model import Project
from .common import clips, timebase


def _t(frames: int, fps: Fraction) -> str:
    """Rational time string n*den/num s."""
    if frames == 0:
        return "0s"
    f = Fraction(frames) / fps
    return f"{f.numerator}/{f.denominator}s"


def render(p: Project, keep_all_cuts: bool = False) -> str:
    src = p.primary
    video = src.video is not None
    fps = timebase(p) if video else Fraction(30)
    # audio-only: dummy 1080p30 sequence format, times in 1/30 s ticks
    w, h = (src.video.width, src.video.height) if src.video else (1920, 1080)
    fd = Fraction(1) / fps
    fmt_name = f"FFVideoFormat{h}p{round(float(fps))}"
    items = clips(p, keep_all_cuts)
    total = items[-1][4] if items else 0
    src_frames = round(src.duration * float(fps))
    rate = src.audio[0].rate if src.audio else 48000
    ch = src.audio[0].channels if src.audio else 2
    name = Path(src.path).stem
    uri = Path(src.path).resolve().as_uri()
    q = quoteattr
    asset = (
        f'    <asset id="r2" name={q(name)} start="0s" duration="{_t(src_frames, fps)}" '
        f'hasAudio="1" audioSources="1" audioChannels="{ch}" audioRate="{rate}"'
        + (' hasVideo="1" format="r1"' if video else "")
        + f'>\n      <media-rep kind="original-media" src={q(uri)}/>\n    </asset>\n'
    )
    clip_xml = []
    for seg, a, b, ra, rb in items:
        attrs = (f'ref="r2" offset="{_t(ra, fps)}" name={q(name)} start="{_t(a, fps)}" '
                 f'duration="{_t(rb - ra, fps)}"')
        if seg.op == "remove":
            attrs += ' enabled="0"'
        if seg.op == "speed":
            clip_xml.append(
                f"          <asset-clip {attrs}>\n"
                f'            <timeMap><timept time="0s" value="0s" interp="linear"/>'
                f'<timept time="{_t(rb - ra, fps)}" value="{_t(b - a, fps)}" interp="linear"/></timeMap>\n'
                f"          </asset-clip>")
        else:
            clip_xml.append(f"          <asset-clip {attrs}/>")
    spine = "\n".join(clip_xml)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
        '<fcpxml version="1.11">\n  <resources>\n'
        f'    <format id="r1" name="{fmt_name}" frameDuration="{fd.numerator}/{fd.denominator}s" '
        f'width="{w}" height="{h}"/>\n'
        f"{asset}  </resources>\n"
        f'  <library>\n    <event name={q(name)}>\n      <project name={q(name + " (claudebolt)")}>\n'
        f'        <sequence format="r1" duration="{_t(total, fps)}" tcStart="0s" tcFormat="NDF" '
        f'audioLayout="stereo" audioRate="48k">\n          <spine>\n'
        f"{spine}\n          </spine>\n        </sequence>\n      </project>\n    </event>\n  </library>\n"
        "</fcpxml>\n"
    )
