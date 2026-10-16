"""Edit commands: the only way to mutate a timeline. Snapshot-based inverse gives undo/redo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .model import EPS, Op, Project, Reason, Segment, normalize


def _split_at(segs: list[Segment], t: float) -> list[Segment]:
    out: list[Segment] = []
    for s in segs:
        if s.start + EPS < t < s.end - EPS:
            a, b = s.model_copy(), s.model_copy()
            a.end, b.start = t, t
            out += [a, b]
        else:
            out.append(s)
    return out


def set_range(segs: list[Segment], start: float, end: float, *, op: Op, speed: float = 1.0,
              zoom: float | None = None, reason: Reason | None = None, confidence: float = 1.0,
              duration: float) -> list[Segment]:
    """Assign attributes to [start, end]; locked pieces are left alone."""
    start, end = max(0.0, start), min(duration, end)
    if end - start <= EPS:
        return segs
    segs = _split_at(_split_at(segs, start), end)
    out = []
    for s in segs:
        if s.start >= start - EPS and s.end <= end + EPS and not s.locked:
            s = s.model_copy(update={
                "op": op, "speed": speed if op == "speed" else 1.0,
                "zoom": s.zoom if zoom is None else zoom,
                "reason": reason if op != "keep" or reason else None,
                "confidence": confidence,
            })
        out.append(s)
    return normalize(out, duration)


class SetRange(BaseModel):
    action: Literal["set_range"] = "set_range"
    start: float
    end: float
    op: Op
    speed: float = 1.0
    zoom: float | None = None
    reason: Reason | None = "manual"
    confidence: float = 1.0

    def apply(self, p: Project) -> str:
        p.segments = set_range(p.segments, self.start, self.end, op=self.op, speed=self.speed,
                               zoom=self.zoom, reason=self.reason, confidence=self.confidence,
                               duration=p.duration)
        return f"{self.op} {self.start:.2f}-{self.end:.2f}"


class ZoomRange(BaseModel):
    action: Literal["zoom_range"] = "zoom_range"
    start: float
    end: float
    zoom: float

    def apply(self, p: Project) -> str:
        segs = _split_at(_split_at(p.segments, self.start), self.end)
        for s in segs:
            if s.start >= self.start - EPS and s.end <= self.end + EPS and not s.locked:
                s.zoom = self.zoom
        p.segments = normalize(segs, p.duration)
        return f"zoom x{self.zoom} {self.start:.2f}-{self.end:.2f}"


class Lock(BaseModel):
    action: Literal["lock"] = "lock"
    start: float
    end: float
    locked: bool = True

    def apply(self, p: Project) -> str:
        segs = _split_at(_split_at(p.segments, self.start), self.end)
        for s in segs:
            if s.start >= self.start - EPS and s.end <= self.end + EPS:
                s.locked = self.locked
        p.segments = normalize(segs, p.duration)
        return f"{'lock' if self.locked else 'unlock'} {self.start:.2f}-{self.end:.2f}"


class ReplaceTimeline(BaseModel):
    """Used by re-detection: keeps locked / manual / agent ranges from the current timeline."""

    action: Literal["replace_timeline"] = "replace_timeline"
    segments: list[Segment]

    def apply(self, p: Project) -> str:
        new = normalize(self.segments, p.duration)
        for old in p.segments:
            if old.locked or old.reason in ("manual", "agent"):
                new = set_range(new, old.start, old.end, op=old.op, speed=old.speed,
                                zoom=old.zoom, reason=old.reason, confidence=old.confidence,
                                duration=p.duration)
                if old.locked:
                    new = _force_lock(new, old.start, old.end, p.duration)
        p.segments = new
        return "re-detect silence"


def _force_lock(segs: list[Segment], a: float, b: float, dur: float) -> list[Segment]:
    segs = _split_at(_split_at(segs, a), b)
    for s in segs:
        if s.start >= a - EPS and s.end <= b + EPS:
            s.locked = True
    return normalize(segs, dur)


class AcceptProposals(BaseModel):
    action: Literal["accept_proposals"] = "accept_proposals"
    ids: list[str]

    def apply(self, p: Project) -> str:
        n = 0
        for pr in p.proposals:
            if pr.id in self.ids and pr.status != "accepted":
                pr.status = "accepted"
                p.segments = set_range(p.segments, pr.start, pr.end, op="remove", reason=pr.kind,
                                       confidence=pr.confidence, duration=p.duration)
                n += 1
        return f"accept {n} proposals"


class RejectProposals(BaseModel):
    action: Literal["reject_proposals"] = "reject_proposals"
    ids: list[str]

    def apply(self, p: Project) -> str:
        n = 0
        for pr in p.proposals:
            if pr.id in self.ids and pr.status == "pending":
                pr.status = "rejected"
                n += 1
        return f"reject {n} proposals"


class CutWords(BaseModel):
    """Remove (or restore) a word range, resolved to a time span over the words."""

    action: Literal["cut_words"] = "cut_words"
    word_range: tuple[int, int]
    restore: bool = False

    def span(self, p: Project) -> tuple[float, float]:
        if p.transcript is None:
            raise ValueError("no transcript: call transcribe first")
        w = p.transcript.words
        a, b = self.word_range
        if not (0 <= a <= b < len(w)):
            raise ValueError(f"word_range {self.word_range} out of range (0..{len(w) - 1})")
        pre = (w[a].start - w[a - 1].end) / 2 if a > 0 else w[a].start
        post = (w[b + 1].start - w[b].end) / 2 if b + 1 < len(w) else p.duration - w[b].end
        return w[a].start - max(0.0, min(pre, 0.15)), w[b].end + max(0.0, min(post, 0.15))

    def apply(self, p: Project) -> str:
        s, e = self.span(p)
        if self.restore:
            p.segments = set_range(p.segments, s, e, op="keep", duration=p.duration)
            return f"restore words {self.word_range}"
        p.segments = set_range(p.segments, s, e, op="remove", reason="manual", duration=p.duration)
        return f"cut words {self.word_range}"


EditOp = Annotated[
    SetRange | ZoomRange | Lock | ReplaceTimeline | AcceptProposals | RejectProposals | CutWords,
    Field(discriminator="action"),
]


class Conflict(Exception):
    def __init__(self, version: int):
        super().__init__(f"version conflict: project is at version {version}")
        self.version = version


@dataclass
class Entry:
    label: str
    actor: str
    before: tuple
    after: tuple


@dataclass
class Editor:
    """Applies ops to a project and keeps undo/redo stacks."""

    project: Project
    undo_stack: list[Entry] = field(default_factory=list)
    redo_stack: list[Entry] = field(default_factory=list)

    def _snap(self) -> tuple:
        p = self.project
        return ([s.model_copy() for s in p.segments], {x.id: x.status for x in p.proposals})

    def _restore(self, snap: tuple) -> None:
        segs, statuses = snap
        p = self.project
        p.segments = [s.model_copy() for s in segs]
        for pr in p.proposals:
            if pr.id in statuses:
                pr.status = statuses[pr.id]

    def apply(self, ops: list, actor: str = "user", expected_version: int | None = None) -> list[str]:
        if expected_version is not None and expected_version != self.project.version:
            raise Conflict(self.project.version)
        before = self._snap()
        labels = [op.apply(self.project) for op in ops]
        self.project.segments = normalize(self.project.segments, self.project.duration)
        self.undo_stack.append(Entry("; ".join(labels), actor, before, self._snap()))
        self.redo_stack.clear()
        self.project.version += 1
        return labels

    def undo(self) -> Entry | None:
        if not self.undo_stack:
            return None
        e = self.undo_stack.pop()
        self._restore(e.before)
        self.redo_stack.append(e)
        self.project.version += 1
        return e

    def redo(self) -> Entry | None:
        if not self.redo_stack:
            return None
        e = self.redo_stack.pop()
        self._restore(e.after)
        self.undo_stack.append(e)
        self.project.version += 1
        return e
