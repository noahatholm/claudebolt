"""Build an ffmpeg filter_complex script from a project's timeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..timeline.model import Project, Segment

MIN_PIECE = 0.002


@dataclass
class Graph:
    inputs: list[tuple[str, float]]  # (path, itsoffset)
    script: str
    duration: float  # expected output duration (seconds)
    has_video: bool
    maps: list[str] = field(default_factory=list)


def atempo_chain(rate: float) -> str:
    parts: list[str] = []
    r = rate
    while r > 2.0 + 1e-9:
        parts.append("atempo=2.0")
        r /= 2.0
    while r < 0.5 - 1e-9:
        parts.append("atempo=0.5")
        r /= 0.5
    parts.append(f"atempo={r:.6f}")
    return ",".join(parts)


def _f(x: float) -> str:
    return f"{x:.6f}"


def frame_align(t: float, fps: float | None, duration: float) -> float:
    if not fps:
        return t
    return min(duration, round(t * fps) / fps)


def pieces(p: Project, segs: list[Segment] | None = None) -> list[Segment]:
    """Renderable (non-removed) segments, frame-aligned for video sources, empties dropped."""
    fps = p.fps
    out: list[Segment] = []
    last_end = 0.0
    for s in (p.segments if segs is None else segs):
        if s.op == "remove":
            continue
        a = frame_align(s.start, fps, p.duration)
        b = frame_align(s.end, fps, p.duration)
        a = max(a, last_end) if fps else a
        if b - a < MIN_PIECE:
            continue
        out.append(s.model_copy(update={"start": a, "end": b}))
        last_end = b
    return out


def build_graph(p: Project, *, video: bool, segs: list[Segment] | None = None,
                fade_ms: float | None = None, scale_height: int | None = None) -> Graph:
    rs = p.render
    pcs = pieces(p, segs)
    if not pcs:
        raise ValueError("nothing to render: every segment is removed")
    fade = (rs.fade_ms if fade_ms is None else fade_ms) / 1000.0
    prim = p.primary
    video = video and prim.video is not None

    # inputs: primary source first, then other sources used by unmuted tracks
    inputs: list[tuple[str, float]] = [(prim.path, 0.0)]
    index = {prim.id: 0}
    prim_track = next((t for t in p.tracks if t.source_id == prim.id), p.tracks[0])
    atracks: list[tuple[int, int]] = []  # (input idx, audio stream)
    for t in p.tracks:
        if t.muted:
            continue
        src = p.source(t.source_id)
        if t.source_id not in index:
            index[t.source_id] = len(inputs)
            inputs.append((src.path, t.offset))
        elif t is not prim_track and t.id != prim_track.id:
            # another stream of an already-opened source
            pass
        atracks.append((index[t.source_id], t.audio_stream))
    if not atracks:
        atracks = [(0, prim_track.audio_stream)]

    lines: list[str] = []
    labels: list[str] = []
    zoom_i = 0
    total = 0.0
    W = H = None
    if video and prim.video:
        W, H = prim.video.width, prim.video.height
        if scale_height and H > scale_height:
            W, H = int(round(W * scale_height / H / 2) * 2), scale_height
    for k, s in enumerate(pcs):
        S, E = s.start, s.end
        rate = s.speed if s.op == "speed" else 1.0
        out_d = (E - S) / rate
        total += out_d
        if video:
            v = f"[0:v]trim=start={_f(S)}:end={_f(E)},setpts=PTS-STARTPTS"
            if rate != 1.0:
                v += f",setpts=PTS/{_f(rate)}"
            z = s.zoom
            if rs.zoom_mode == "alternate" and s.op == "keep":
                if zoom_i % 2 == 1:
                    z = max(z, rs.zoom)
                zoom_i += 1
            if z != 1.0:
                v += f",crop=iw/{_f(z)}:ih/{_f(z)}"
            if z != 1.0 or (W, H) != (prim.video.width, prim.video.height):
                v += f",scale={W}:{H}:flags=bicubic"
            v += f",setsar=1[v{k}]"
            lines.append(v)
        branch = []
        for j, (ii, st) in enumerate(atracks):
            # -itsoffset on the input shifts the stream, so primary-time trims line up across tracks
            a = f"[{ii}:a:{st}]atrim=start={_f(S)}:end={_f(E)},asetpts=PTS-STARTPTS"
            a_lab = f"[a{k}_{j}]" if len(atracks) > 1 else f"[a{k}]"
            lines.append(a + a_lab)
            branch.append(a_lab)
        post = []
        if len(atracks) > 1:
            lines.append("".join(branch) + f"amix=inputs={len(atracks)}:duration=longest:normalize=0[am{k}]")
            src_lab = f"[am{k}]"
        else:
            src_lab = branch[0]
        if rate != 1.0:
            post.append(atempo_chain(rate))
        if s.op == "speed" and p.detection.mute_speed:
            post.append("volume=0")
        if fade > 0 and out_d > 4 * fade:
            post.append(f"afade=t=in:d={_f(fade)}")
            post.append(f"afade=t=out:st={_f(out_d - fade)}:d={_f(fade)}")
        post.append(f"apad=whole_dur={_f(out_d)}")  # tempo filters can come up a few ms short
        post.append(f"atrim=end={_f(out_d)}")
        post.append("asetpts=PTS-STARTPTS")
        lines.append(f"{src_lab}{','.join(post)}[ao{k}]")
        labels.append(f"[v{k}]" if video else "")
        labels[-1] += f"[ao{k}]"
    n = len(pcs)
    lines.append("".join(labels) + f"concat=n={n}:v={1 if video else 0}:a=1" +
                 ("[vout][aout]" if video else "[aout]"))
    maps = ["[vout]", "[aout]"] if video else ["[aout]"]
    return Graph(inputs=inputs, script=";\n".join(lines), duration=total, has_video=video, maps=maps)
