"""Core data model: Project, Source, Segment, Timeline, Proposal, Transcript."""

from __future__ import annotations

import bisect
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from ..config import CleanupSettings, DetectionSettings, RenderSettings

Op = Literal["keep", "remove", "speed"]
Reason = Literal["silence", "filler", "false_start", "retake", "manual", "agent"]
EPS = 1e-6


class AudioStream(BaseModel):
    index: int
    channels: int = 1
    rate: int = 0
    codec: str = ""
    lang: str | None = None
    bits: int | None = None


class VideoInfo(BaseModel):
    width: int
    height: int
    fps: float
    codec: str = ""
    vfr: bool = False
    fps_rational: str = "30/1"


class Source(BaseModel):
    id: str
    path: str
    kind: Literal["video", "audio"]
    duration: float
    sha256: str = ""
    video: VideoInfo | None = None
    audio: list[AudioStream] = Field(default_factory=list)
    format: str = ""


class Track(BaseModel):
    id: str
    source_id: str
    audio_stream: int = 0
    offset: float = 0.0
    muted: bool = False
    role: Literal["primary", "aux"] = "primary"


class Segment(BaseModel):
    start: float
    end: float
    op: Op = "keep"
    speed: float = 1.0
    zoom: float = 1.0
    reason: Reason | None = None
    confidence: float = 1.0
    locked: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def out_duration(self) -> float:
        if self.op == "remove":
            return 0.0
        return self.duration / (self.speed if self.op == "speed" else 1.0)

    def key(self) -> tuple:
        return (self.op, round(self.speed, 6), round(self.zoom, 6), self.reason, self.locked)


class Word(BaseModel):
    text: str
    start: float
    end: float
    prob: float = 1.0
    speaker: str | None = None


class Transcript(BaseModel):
    model: str = ""
    language: str = "en"
    words: list[Word] = Field(default_factory=list)
    sentences: list[tuple[int, int]] = Field(default_factory=list)  # inclusive word idx


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    kind: Literal["filler", "false_start", "retake"]
    start: float
    end: float
    word_range: tuple[int, int] | None = None
    text: str = ""
    confidence: float = 1.0
    note: str = ""
    status: Literal["pending", "accepted", "rejected"] = "pending"


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    version: int = 0
    sources: list[Source] = Field(default_factory=list)
    tracks: list[Track] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    transcript: Transcript | None = None
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    cleanup: CleanupSettings = Field(default_factory=CleanupSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    project_path: str | None = None

    # ------------------------------------------------------------------ helpers
    @property
    def primary(self) -> Source:
        t = next((t for t in self.tracks if t.role == "primary"), self.tracks[0])
        return self.source(t.source_id)

    def source(self, sid: str) -> Source:
        return next(s for s in self.sources if s.id == sid)

    @property
    def duration(self) -> float:
        return self.primary.duration

    @property
    def output_duration(self) -> float:
        return sum(s.out_duration for s in self.segments)

    @property
    def fps(self) -> float | None:
        v = self.primary.video
        return v.fps if v else None


# ---------------------------------------------------------------- normalize
def normalize(segs: list[Segment], duration: float) -> list[Segment]:
    """Return segments tiling [0, duration] exactly, with equal neighbours merged. Idempotent."""
    items = sorted((s.model_copy() for s in segs), key=lambda s: (s.start, s.end))
    out: list[Segment] = []
    cur = 0.0
    for s in items:
        s.start = max(s.start, 0.0)
        s.end = min(s.end, duration)
        if s.end - s.start <= EPS:
            continue
        if s.start < cur:  # overlap: later segment loses the overlap
            s.start = cur
            if s.end - s.start <= EPS:
                continue
        if s.start - cur > EPS:
            out.append(Segment(start=cur, end=s.start))
        out.append(s)
        cur = s.end
    if duration - cur > EPS:
        out.append(Segment(start=cur, end=duration))
    merged: list[Segment] = []
    for s in out:
        if merged and merged[-1].key() == s.key() and abs(merged[-1].end - s.start) <= EPS:
            merged[-1].end = s.end
            merged[-1].confidence = min(merged[-1].confidence, s.confidence)
        else:
            merged.append(s)
    if merged:
        merged[0].start = 0.0
        merged[-1].end = duration
        for a, b in zip(merged, merged[1:]):
            b.start = a.end
    return merged or [Segment(start=0.0, end=duration)]


# ---------------------------------------------------------------- time mapping
def _out_starts(segs: list[Segment]) -> list[float]:
    acc, res = 0.0, []
    for s in segs:
        res.append(acc)
        acc += s.out_duration
    return res


def source_to_output(segs: list[Segment], t: float) -> float:
    """Piecewise-linear map; removed spans collapse to a point."""
    outs = _out_starts(segs)
    for s, o in zip(segs, outs):
        if t <= s.end + EPS:
            if t <= s.start:
                return o
            if s.op == "remove":
                return o
            return o + (t - s.start) / (s.speed if s.op == "speed" else 1.0)
    return outs[-1] + segs[-1].out_duration if segs else 0.0


def output_to_source(segs: list[Segment], t: float) -> float:
    outs = _out_starts(segs)
    i = bisect.bisect_right(outs, t) - 1
    # skip zero-length (removed) segments that share the same output offset
    while i >= 0 and segs[i].op == "remove":
        i -= 1
    if i < 0:
        return segs[0].start if segs else 0.0
    s = segs[i]
    rate = s.speed if s.op == "speed" else 1.0
    return min(s.end, s.start + (t - outs[i]) * rate)
