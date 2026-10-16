"""The single service layer behind the CLI, REST API and MCP server."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

import numpy as np

from . import export as exporters
from .cleanup.proposals import run_cleanup as _run_cleanup
from .config import AppSettings, DetectionSettings, cache_dir, load_settings, save_settings
from .detect import pipeline, threshold
from .jobs import EventBus, JobManager
from .media import ffmpeg
from .media.decode import Analysis, decode, resample_peaks
from .media.probe import probe
from .render import render as renderer
from .timeline import store
from .timeline.model import Project, Segment, Track, normalize, output_to_source, source_to_output
from .timeline.ops import (
    AcceptProposals,
    Conflict,
    CutWords,
    Editor,
    Lock,
    RejectProposals,
    ReplaceTimeline,
    SetRange,
    ZoomRange,
)
from .transcribe import models as tmodels
from .transcribe import sentences, whisper

__all__ = ["Conflict", "Service", "ServiceError"]


class ServiceError(Exception):
    """An error with an actionable hint (surfaced as {error, hint} to agents)."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def _round(x: float, n: int = 3) -> float:
    return round(float(x), n)


class Service:
    def __init__(self, sandbox: bool = False, settings: AppSettings | None = None) -> None:
        self.sandbox = sandbox
        self.settings = settings or load_settings()
        self.bus = EventBus()
        self.jobs = JobManager(self.bus)
        self._editors: dict[str, Editor] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._allowed: set[Path] = set()
        self._analyses: dict[tuple[str, int], Analysis] = {}
        self._analysis_locks: dict[tuple[str, int], threading.Lock] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._reg = threading.Lock()

    # ------------------------------------------------------------------ plumbing
    def _editor(self, pid: str) -> Editor:
        try:
            return self._editors[pid]
        except KeyError:
            raise ServiceError(f"unknown project {pid!r}", "call open_media or list_projects") from None

    def _lock(self, pid: str) -> threading.RLock:
        with self._reg:
            return self._locks.setdefault(pid, threading.RLock())

    def project(self, pid: str) -> Project:
        return self._editor(pid).project

    def _allow(self, path: str | Path) -> None:
        self._allowed.add(Path(path).resolve())

    def check_path(self, path: str | Path, write: bool = False) -> Path:
        p = Path(path).resolve()
        if not self.sandbox:
            return p
        dirs = set(self._allowed) | {cache_dir().resolve()}
        if self.settings.output_dir:
            dirs.add(Path(self.settings.output_dir).resolve())
        for d in dirs:
            if p == d or d in p.parents:
                return p
        raise ServiceError(f"path not allowed: {p}",
                           "only opened media, their folders and the output folder are accessible; "
                           "call open_media on the file first")

    def _emit_changed(self, pid: str, labels: list[str], actor: str) -> None:
        p = self.project(pid)
        self.bus.publish({"type": "timeline.changed", "project": pid, "version": p.version,
                          "op": labels, "actor": actor})
        self._autosave(pid)

    def _autosave(self, pid: str) -> None:
        p = self.project(pid)
        if not p.project_path:
            return
        with self._reg:
            t = self._timers.pop(pid, None)
            if t:
                t.cancel()
            t = threading.Timer(2.0, self._save_quiet, args=(pid,))
            t.daemon = True
            self._timers[pid] = t
            t.start()

    def _save_quiet(self, pid: str) -> None:
        try:
            with self._lock(pid):
                store.save(self.project(pid))
        except Exception:
            pass

    def flush(self) -> None:
        """Save every project that has a path (called on shutdown)."""
        with self._reg:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
        for pid, ed in self._editors.items():
            if ed.project.project_path:
                self._save_quiet(pid)

    def analysis(self, p: Project, track: int = 0, on_progress=None, cancel=None) -> Analysis:
        t = p.tracks[track]
        src = p.source(t.source_id)
        key = (src.sha256, t.audio_stream)
        with self._reg:
            lock = self._analysis_locks.setdefault(key, threading.Lock())
        # one decode per stream: concurrent requests (peaks + analyze on first open) share its cache files
        with lock:
            if key not in self._analyses:
                self._analyses[key] = decode(src, t.audio_stream, on_progress, cancel)
            return self._analyses[key]

    # ------------------------------------------------------------------ projects
    def open_media(self, paths: list[str], project_path: str | None = None) -> dict:
        if not paths:
            raise ServiceError("no paths given")
        for pth in paths:
            self._allow(Path(pth).parent)
        if project_path:
            self._allow(Path(project_path).parent)
        primary = Path(paths[0])
        default_proj = Path(project_path) if project_path else store.default_path(primary)
        loaded = False
        if default_proj.exists():
            try:
                p = store.load(default_proj)
                for s in p.sources:
                    if not Path(s.path).exists():
                        raise FileNotFoundError(s.path)
                loaded = True
            except Exception:
                p = None  # type: ignore[assignment]
        if not loaded:
            try:
                sources = [probe(pth, f"s{i}") for i, pth in enumerate(paths)]
            except FileNotFoundError as e:
                raise ServiceError(f"file not found: {e}", "check the path") from e
            except ffmpeg.FFmpegError as e:
                raise ServiceError(str(e), "the file may not be a supported media file") from e
            tracks = [Track(id=f"t{i}", source_id=s.id, role="primary" if i == 0 else "aux")
                      for i, s in enumerate(sources)]
            p = Project(sources=sources, tracks=tracks,
                        segments=[Segment(start=0.0, end=sources[0].duration)],
                        detection=self.settings.detection.model_copy(),
                        cleanup=self.settings.cleanup.model_copy(),
                        render=self.settings.render.model_copy())
            p.project_path = str(default_proj)
            if len(sources) > 1:
                p.detection.combine = "any"
        else:
            # keep ids stable for reopened projects
            pass
        existing = next((e.project for e in self._editors.values()
                         if e.project.project_path == p.project_path), None)
        if existing is not None:
            return self.describe(existing.id) | {"already_open": True}
        self._editors[p.id] = Editor(p)
        return self.describe(p.id) | {"loaded_existing": loaded}

    def describe(self, pid: str) -> dict:
        p = self.project(pid)
        return {
            "id": p.id, "version": p.version, "project_path": p.project_path,
            "sources": [s.model_dump(exclude={"sha256"}) for s in p.sources],
            "tracks": [t.model_dump() for t in p.tracks],
            "duration": _round(p.duration), "output_duration": _round(p.output_duration),
            "has_transcript": p.transcript is not None,
            "warnings": (["variable frame rate video: cuts may drift; re-encode to a constant "
                          "frame rate first (ffmpeg -vf fps=30)"]
                         if p.primary.video and p.primary.video.vfr else []),
            "proposals": len(p.proposals),
        }

    def list_projects(self) -> list[dict]:
        return [self.describe(pid) for pid in self._editors]

    def save_project(self, pid: str, path: str | None = None) -> str:
        with self._lock(pid):
            return str(store.save(self.project(pid), self.check_path(path, True) if path else None))

    def close_project(self, pid: str) -> dict:
        self._save_quiet(pid)
        self._editors.pop(pid, None)
        return {"closed": pid}

    def get_project(self, pid: str) -> Project:
        return self.project(pid)

    # ------------------------------------------------------------------ tracks
    def set_track(self, pid: str, track: int, offset: float | None = None,
                  muted: bool | None = None) -> dict:
        with self._lock(pid):
            p = self.project(pid)
            if not 0 <= track < len(p.tracks):
                raise ServiceError(f"no track {track}", f"project has {len(p.tracks)} tracks")
            t = p.tracks[track]
            if offset is not None:
                t.offset = offset
            if muted is not None:
                t.muted = muted
            p.version += 1
        self.bus.publish({"type": "tracks.changed", "project": pid, "version": p.version})
        self._autosave(pid)
        return self.describe(pid)

    def auto_sync(self, pid: str) -> dict:
        """Estimate each aux track's offset against the primary by envelope cross-correlation."""
        from .detect.multitrack import estimate_offset

        p = self.project(pid)
        if len(p.tracks) < 2:
            raise ServiceError("need at least two tracks to sync", "open_media with several files")
        ref = self.analysis(p, 0).pcm()
        found = {}
        for i in range(1, len(p.tracks)):
            found[i] = round(estimate_offset(ref, self.analysis(p, i).pcm()), 4)
            self.set_track(pid, i, offset=found[i])
        return {"offsets": found}

    # ------------------------------------------------------------------ analysis / detection
    def analyze_audio(self, pid: str, track: int = 0) -> dict:
        p = self.project(pid)
        a = self.analysis(p, track)
        return threshold.analyze(a.levels) | {"duration": _round(a.duration)}

    def get_levels(self, pid: str, start: float = 0.0, end: float | None = None,
                   resolution: int = 200, track: int = 0) -> dict:
        p = self.project(pid)
        a = self.analysis(p, track)
        end = p.duration if end is None else end
        i, j = max(0, int(start / 0.04)), max(1, int(np.ceil(end / 0.04)))
        lv = a.levels[i:j]
        resolution = max(1, min(500, resolution))
        if len(lv) > resolution:
            edges = np.linspace(0, len(lv), resolution + 1).astype(int)
            lv = np.array([lv[edges[k]:max(edges[k + 1], edges[k] + 1)].max()
                           for k in range(resolution)])
        step = (end - start) / max(1, len(lv))
        return {"start": start, "end": end, "step": _round(step, 4),
                "db": [round(float(x), 1) for x in lv]}

    def get_peaks(self, pid: str, px: int = 2000, track: int = 0) -> dict:
        p = self.project(pid)
        a = self.analysis(p, track)
        pk = resample_peaks(a.peaks, max(1, min(px, 20000)))
        return {"duration": _round(a.duration), "peaks": np.round(pk, 3).tolist()}

    def detect_silence(self, pid: str, overrides: dict | None = None, actor: str = "user",
                       on_progress=None, cancel=None) -> dict:
        ed = self._editor(pid)
        with self._lock(pid):
            p = ed.project
            if overrides:
                p.detection = p.detection.model_copy(update=overrides)
                p.detection = DetectionSettings.model_validate(p.detection.model_dump())
            before = p.output_duration
            try:
                segs, thr = pipeline.detect(p, p.detection, on_progress, cancel)
            except Exception as e:
                if e.__class__.__name__ == "VadUnavailable":
                    raise ServiceError(str(e), "use mode='rms' or install the VAD model") from e
                raise
            labels = ed.apply([ReplaceTimeline(segments=segs)], actor)
            summ = self.summary(p)
        self._emit_changed(pid, labels, actor)
        return summ | {"threshold_db": _round(thr, 1),
                       "output_duration_before": _round(before)}

    # ------------------------------------------------------------------ timeline views
    def summary(self, p: Project) -> dict:
        removed = [s for s in p.segments if s.op == "remove"]
        by: dict[str, dict] = {}
        for s in p.segments:
            if s.op != "keep":
                r = s.reason or "other"
                d = by.setdefault(f"{s.op}:{r}", {"count": 0, "seconds": 0.0})
                d["count"] += 1
                d["seconds"] = _round(d["seconds"] + s.duration)
        longest = sorted(removed, key=lambda s: -s.duration)[:20]
        rem_s = sum(s.duration for s in removed)
        return {
            "project": p.id, "version": p.version,
            "source_duration": _round(p.duration), "output_duration": _round(p.output_duration),
            "removed_seconds": _round(rem_s),
            "percent_removed": _round(100 * (1 - p.output_duration / p.duration), 1) if p.duration else 0,
            "segments": len(p.segments), "by_reason": by,
            "longest_removes": [self._seg(p, s) for s in longest],
        }

    def _seg(self, p: Project, s: Segment) -> dict:
        d = {"src_start": _round(s.start), "src_end": _round(s.end),
             "out_start": _round(source_to_output(p.segments, s.start)),
             "out_end": _round(source_to_output(p.segments, s.end)),
             "op": s.op, "reason": s.reason, "locked": s.locked}
        if s.op == "speed":
            d["speed"] = s.speed
        if s.zoom != 1.0:
            d["zoom"] = s.zoom
        return d

    def get_timeline(self, pid: str, detail: str = "summary", range: tuple[float, float] | None = None,
                     cursor: int = 0, limit: int = 200, time_base: str = "source") -> dict:
        p = self.project(pid)
        if detail == "summary":
            return self.summary(p)
        segs = p.segments
        if range:
            a, b = range
            if time_base == "output":
                a, b = output_to_source(segs, a), output_to_source(segs, b)
            segs = [s for s in segs if s.end > a and s.start < b]
        page = segs[cursor:cursor + limit]
        nxt = cursor + limit if cursor + limit < len(segs) else None
        return {"project": pid, "version": p.version, "total": len(segs),
                "segments": [self._seg(p, s) for s in page], "next_cursor": nxt}

    def map_time(self, pid: str, t: float, from_: str = "source") -> dict:
        p = self.project(pid)
        if from_ == "source":
            return {"source": t, "output": _round(source_to_output(p.segments, t))}
        return {"output": t, "source": _round(output_to_source(p.segments, t))}

    # ------------------------------------------------------------------ edits
    def _convert_ops(self, p: Project, raw: list[dict], actor: str, time_base: str) -> list:
        reason = "agent" if actor == "agent" else "manual"
        ops = []
        for r in raw:
            act = r.get("action")
            tb = r.get("time_base", time_base)
            if "word_range" in r and r["word_range"] is not None:
                if act not in ("keep", "remove"):
                    raise ServiceError(f"word_range only supports keep/remove, got {act!r}")
                ops.append(CutWords(word_range=tuple(r["word_range"]), restore=act == "keep"))
                continue
            if "start" not in r or "end" not in r:
                raise ServiceError(f"op {r!r} needs start/end or word_range")
            a, b = float(r["start"]), float(r["end"])
            if b <= a:
                raise ServiceError(f"end must be after start in {r!r}")
            if tb == "output":
                a, b = output_to_source(p.segments, a), output_to_source(p.segments, b)
            if act in ("keep", "remove"):
                ops.append(SetRange(start=a, end=b, op=act, reason=reason))
            elif act == "speed":
                ops.append(SetRange(start=a, end=b, op="speed", speed=float(r.get("speed", 2.0)),
                                    reason=reason))
            elif act == "zoom":
                ops.append(ZoomRange(start=a, end=b, zoom=float(r.get("zoom", 1.25))))
            elif act in ("lock", "unlock"):
                ops.append(Lock(start=a, end=b, locked=act == "lock"))
            else:
                raise ServiceError(f"unknown action {act!r}",
                                   "use keep|remove|speed|zoom|lock|unlock")
        return ops

    def apply_edits(self, pid: str, ops: list[dict], expected_version: int | None = None,
                    actor: str = "user", time_base: str = "source") -> dict:
        ed = self._editor(pid)
        with self._lock(pid):
            p = ed.project
            try:
                model_ops = self._convert_ops(p, ops, actor, time_base)
                labels = ed.apply(model_ops, actor, expected_version)
            except Conflict as c:
                return {"conflict": True, "version": c.version,
                        "hint": "re-read the timeline and retry with the new version"}
            except ValueError as e:
                raise ServiceError(str(e)) from e
            summ = self.summary(p)
        self._emit_changed(pid, labels, actor)
        return summ | {"applied": labels}

    def undo(self, pid: str, steps: int = 1, actor: str = "user") -> dict:
        return self._history(pid, steps, actor, undo=True)

    def redo(self, pid: str, steps: int = 1, actor: str = "user") -> dict:
        return self._history(pid, steps, actor, undo=False)

    def _history(self, pid: str, steps: int, actor: str, undo: bool) -> dict:
        ed = self._editor(pid)
        labels: list[str] = []
        with self._lock(pid):
            for _ in range(max(1, steps)):
                e = ed.undo() if undo else ed.redo()
                if e is None:
                    break
                labels.append(("undo " if undo else "redo ") + e.label)
            summ = self.summary(ed.project)
        if labels:
            self._emit_changed(pid, labels, actor)
        return summ | {"applied": labels}

    # ------------------------------------------------------------------ transcript + cleanup
    def list_models(self) -> list[dict]:
        return tmodels.list_models()

    def download_model(self, name: str) -> dict:
        job = self.jobs.submit("download_model", lambda prog, c: str(tmodels.download(name, prog)))
        return job.public()

    def transcribe(self, pid: str, model: str | None = None, language: str | None = None) -> dict:
        p = self.project(pid)
        model = model or self.settings.whisper_model
        if not tmodels.installed(model) and not whisper.load_cached(
                p.primary, p.tracks[0].audio_stream, model):
            raise ServiceError(f"model {model!r} is not downloaded",
                               f"call download_model with name='{model}' first")

        def work(prog, cancel):
            a = self.analysis(p, 0, lambda f: prog(f * 0.1), cancel)
            tr = whisper.transcribe(p.primary, p.tracks[0].audio_stream, a, model, language,
                                    lambda f: prog(0.1 + 0.9 * f), cancel)
            with self._lock(pid):
                p.transcript = tr
                p.version += 1
            self.bus.publish({"type": "transcript.changed", "project": pid, "version": p.version})
            self._autosave(pid)
            return {"model": tr.model, "language": tr.language, "words": len(tr.words),
                    "sentences": len(tr.sentences)}

        return self.jobs.submit("transcribe", work, pid).public()

    def import_transcript(self, pid: str, path: str) -> dict:
        path = str(self.check_path(path))
        p = self.project(pid)
        tr = sentences.import_srt(path) if path.lower().endswith(".srt") else sentences.import_json(path)
        with self._lock(pid):
            p.transcript = tr
            p.version += 1
        self.bus.publish({"type": "transcript.changed", "project": pid, "version": p.version})
        return {"words": len(tr.words), "sentences": len(tr.sentences)}

    def set_transcript(self, pid: str, transcript) -> None:
        p = self.project(pid)
        with self._lock(pid):
            p.transcript = transcript
            p.version += 1

    def get_transcript(self, pid: str, start: float | None = None, end: float | None = None,
                       cursor: int = 0, limit: int = 500, include_proposals: bool = True) -> dict:
        p = self.project(pid)
        if p.transcript is None:
            raise ServiceError("no transcript yet", "call transcribe first")
        words = list(enumerate(p.transcript.words))
        if start is not None or end is not None:
            lo, hi = start or 0.0, end if end is not None else p.duration
            words = [(i, w) for i, w in words if w.end > lo and w.start < hi]
        page = words[cursor:cursor + limit]
        seg_remove = [(s.start, s.end) for s in p.segments if s.op == "remove"]

        def removed(w) -> bool:
            m = (w.start + w.end) / 2
            return any(a <= m <= b for a, b in seg_remove)

        res = {"project": pid, "model": p.transcript.model, "total_words": len(p.transcript.words),
               "words": [{"i": i, "text": w.text.strip(), "start": _round(w.start),
                          "end": _round(w.end), "removed": removed(w)} for i, w in page],
               "next_cursor": cursor + limit if cursor + limit < len(words) else None}
        if include_proposals and page:
            lo_i, hi_i = page[0][0], page[-1][0]
            res["proposals"] = [self._prop(p, x) for x in p.proposals
                                if x.word_range and x.word_range[1] >= lo_i and x.word_range[0] <= hi_i]
        return res

    def search_transcript(self, pid: str, query: str, regex: bool = False) -> dict:
        import re

        p = self.project(pid)
        if p.transcript is None:
            raise ServiceError("no transcript yet", "call transcribe first")
        words = p.transcript.words
        text = ""
        offs = []
        for w in words:
            offs.append(len(text))
            text += w.text.strip() + " "
        pat = re.compile(query if regex else re.escape(query), re.IGNORECASE)
        out = []
        import bisect

        for m in pat.finditer(text):
            a = bisect.bisect_right(offs, m.start()) - 1
            b = max(a, bisect.bisect_right(offs, max(m.start(), m.end() - 1)) - 1)
            out.append({"word_range": [a, b], "start": _round(words[a].start),
                        "end": _round(words[b].end), "text": text[m.start():m.end()]})
            if len(out) >= 200:
                break
        return {"matches": out}

    def run_cleanup(self, pid: str, kinds: list[str] | None = None, fillers: list[str] | None = None,
                    min_confidence: float | None = None) -> dict:
        p = self.project(pid)
        if p.transcript is None:
            raise ServiceError("no transcript yet", "call transcribe first")
        cfg = p.cleanup.model_copy()
        if fillers is not None:
            cfg.fillers = fillers
        if min_confidence is not None:
            cfg.min_confidence = min_confidence
        kinds = kinds or cfg.kinds
        with self._lock(pid):
            new = _run_cleanup(p.transcript, cfg, p.duration, kinds)
            keep = [x for x in p.proposals if x.kind not in kinds or x.status != "pending"]
            known = {(x.kind, x.word_range) for x in keep}
            p.proposals = keep + [x for x in new if (x.kind, x.word_range) not in known]
            p.version += 1
        self.bus.publish({"type": "proposals.changed", "project": pid, "version": p.version})
        self._autosave(pid)
        grouped: dict[str, int] = {}
        for x in new:
            grouped[x.kind] = grouped.get(x.kind, 0) + 1
        return {"version": p.version, "created": grouped, "pending": sum(
            1 for x in p.proposals if x.status == "pending")}

    def _prop(self, p: Project, x, context: int = 0) -> dict:
        d = {"id": x.id, "kind": x.kind, "start": _round(x.start), "end": _round(x.end),
             "word_range": list(x.word_range) if x.word_range else None, "text": x.text,
             "confidence": x.confidence, "status": x.status, "note": x.note}
        if context and p.transcript and x.word_range:
            w = p.transcript.words
            a, b = x.word_range
            d["context_before"] = " ".join(t.text.strip() for t in w[max(0, a - context):a])
            d["context_after"] = " ".join(t.text.strip() for t in w[b + 1:b + 1 + context])
        return d

    def list_proposals(self, pid: str, kind: str | None = None, status: str | None = None,
                       cursor: int = 0, limit: int = 100) -> dict:
        p = self.project(pid)
        items = [x for x in p.proposals if (not kind or x.kind == kind)
                 and (not status or x.status == status)]
        page = items[cursor:cursor + limit]
        return {"total": len(items), "proposals": [self._prop(p, x, 5) for x in page],
                "next_cursor": cursor + limit if cursor + limit < len(items) else None}

    def _select(self, p: Project, ids: list[str] | None, selector: dict | None,
                status: str) -> list[str]:
        if ids:
            return ids
        sel = selector or {}
        return [x.id for x in p.proposals if x.status == status
                and (not sel.get("kind") or x.kind == sel["kind"])
                and x.confidence >= float(sel.get("min_confidence", 0.0))]

    def accept_proposals(self, pid: str, ids: list[str] | None = None, selector: dict | None = None,
                         actor: str = "user") -> dict:
        ed = self._editor(pid)
        with self._lock(pid):
            chosen = self._select(ed.project, ids, selector, "pending")
            labels = ed.apply([AcceptProposals(ids=chosen)], actor)
            summ = self.summary(ed.project)
        self._emit_changed(pid, labels, actor)
        return summ | {"accepted": len(chosen)}

    def reject_proposals(self, pid: str, ids: list[str] | None = None, selector: dict | None = None,
                         actor: str = "user") -> dict:
        ed = self._editor(pid)
        with self._lock(pid):
            chosen = self._select(ed.project, ids, selector, "pending")
            labels = ed.apply([RejectProposals(ids=chosen)], actor)
            summ = self.summary(ed.project)
        self._emit_changed(pid, labels, actor)
        return summ | {"rejected": len(chosen)}

    # ------------------------------------------------------------------ render / export
    def _out_path(self, p: Project, output_path: str | None, suffix: str | None = None) -> Path:
        if output_path:
            return self.check_path(output_path, True)
        base = Path(self.settings.output_dir) if self.settings.output_dir else Path(
            p.primary.path).parent
        ext = suffix or ("." + (p.render.container or (p.primary.format or "mp4")))
        return self.check_path(base / (Path(p.primary.path).stem + ".edited" + ext), True)

    def render(self, pid: str, output_path: str | None = None, settings: dict | None = None) -> dict:
        ed = self._editor(pid)
        with self._lock(pid):
            snap = ed.project.model_copy(deep=True)
        if settings:
            snap.render = snap.render.model_copy(update=settings)
        out = self._out_path(snap, output_path)

        def work(prog, cancel):
            res = renderer.render(snap, out, on_progress=prog, cancel=cancel)
            res["duration"] = probe_duration(res["path"])
            return res

        return self.jobs.submit("render", work, pid).public()

    def preview_clip(self, pid: str, start: float, end: float, time_base: str = "source") -> dict:
        ed = self._editor(pid)
        with self._lock(pid):
            snap = ed.project.model_copy(deep=True)
        if time_base == "output":
            start, end = output_to_source(snap.segments, start), output_to_source(snap.segments, end)
        segs = renderer.clip_segments(snap, start, end)
        if not any(s.op != "remove" for s in segs):
            raise ServiceError("that range is entirely removed", "pick a range that includes kept audio")
        key = hashlib.sha1(f"{pid}{snap.version}{start:.3f}{end:.3f}".encode()).hexdigest()[:12]
        ext = "mp4" if snap.primary.video else "mp3"
        out = cache_dir() / "previews" / f"{key}.{ext}"

        def work(prog, cancel):
            if not out.exists():
                renderer.render(snap, out, segments=segs, preview=True, on_progress=prog, cancel=cancel)
            return {"path": str(out), "source_range": [_round(start), _round(end)]}

        if end - start <= 2.0:
            return {"status": "done", "result": work(lambda f: None, threading.Event())}
        return self.jobs.submit("preview", work, pid).public()

    def export(self, pid: str, fmt: str, path: str | None = None, keep_all_cuts: bool = False) -> dict:
        p = self.project(pid)
        if path is None:
            path = str(self._out_path(p, None, exporters.EXT.get(fmt, ".txt")).with_name(
                Path(p.primary.path).stem + ".edited" + exporters.EXT.get(fmt, ".txt")))
        out = self.check_path(path, True)
        try:
            return {"path": exporters.export(p, fmt, out, keep_all_cuts)}
        except ValueError as e:
            raise ServiceError(str(e)) from e

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        return self.settings.model_dump()

    def update_settings(self, patch: dict) -> dict:
        merged = self.settings.model_dump()
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        self.settings = AppSettings.model_validate(merged)
        save_settings(self.settings)
        return self.get_settings()

    # ------------------------------------------------------------------ jobs
    def get_job(self, job_id: str) -> dict:
        try:
            return self.jobs.get(job_id).public()
        except KeyError as e:
            raise ServiceError(str(e), "call list_jobs") from e

    def cancel_job(self, job_id: str) -> dict:
        try:
            return self.jobs.cancel(job_id).public()
        except KeyError as e:
            raise ServiceError(str(e), "call list_jobs") from e

    def list_jobs(self) -> list[dict]:
        return self.jobs.list()

    def wait_job(self, job_id: str, timeout: float | None = None) -> dict:
        return self.jobs.wait(job_id, timeout).public()


def probe_duration(path: str) -> float:
    return probe(path).duration


_ = (normalize, Any)
