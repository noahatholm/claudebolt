"""Thread-based job queue with progress, cancel and an event bus."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .media.ffmpeg import Cancelled


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            self._subs.append(fn)

        def unsub() -> None:
            with self._lock:
                if fn in self._subs:
                    self._subs.remove(fn)

        return unsub

    def publish(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(event)
            except Exception:  # a broken subscriber must never break a job
                pass


@dataclass
class Job:
    id: str
    kind: str
    project: str | None
    status: str = "queued"  # queued|running|done|failed|cancelled
    progress: float = 0.0
    result: Any = None
    error: str | None = None
    hint: str | None = None
    created: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict:
        d = {"job_id": self.id, "kind": self.kind, "project": self.project, "status": self.status,
             "progress": round(self.progress, 3)}
        if self.status == "done":
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
            if self.hint:
                d["hint"] = self.hint
        return d


class JobManager:
    """Default: 1 render at a time, plus 1 transcribe/detect in parallel."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.jobs: dict[str, Job] = {}
        self._pools = {"render": ThreadPoolExecutor(1, "render"),
                       "work": ThreadPoolExecutor(2, "work")}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[Callable[[float], None], threading.Event], Any],
               project: str | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, project=project)
        with self._lock:
            self.jobs[job.id] = job
        pool = self._pools["render" if kind in ("render", "preview") else "work"]
        last = [0.0]

        def progress(f: float) -> None:
            job.progress = f
            now = time.monotonic()
            if f >= 1.0 or now - last[0] > 0.2:
                last[0] = now
                self.bus.publish({"type": "job.progress", "job": job.id, "kind": kind,
                                  "progress": round(f, 3)})

        def run() -> None:
            if job.cancel.is_set():
                job.status = "cancelled"
                job.done.set()
                return
            job.status = "running"
            try:
                job.result = fn(progress, job.cancel)
                job.status = "done"
                job.progress = 1.0
                self.bus.publish({"type": "job.done", "job": job.id, "kind": kind,
                                  "result": job.result})
            except Cancelled:
                job.status = "cancelled"
                self.bus.publish({"type": "job.failed", "job": job.id, "kind": kind,
                                  "error": "cancelled"})
            except Exception as e:
                job.status = "failed"
                job.error = str(e)
                job.hint = getattr(e, "hint", None)
                if not isinstance(e, (ValueError, RuntimeError, FileNotFoundError)):
                    job.error += "\n" + traceback.format_exc(limit=3)
                self.bus.publish({"type": "job.failed", "job": job.id, "kind": kind,
                                  "error": job.error})
            finally:
                job.done.set()

        pool.submit(run)
        return job

    def get(self, job_id: str) -> Job:
        try:
            return self.jobs[job_id]
        except KeyError:
            raise KeyError(f"unknown job {job_id!r}") from None

    def cancel(self, job_id: str) -> Job:
        j = self.get(job_id)
        j.cancel.set()
        return j

    def wait(self, job_id: str, timeout: float | None = None) -> Job:
        j = self.get(job_id)
        j.done.wait(timeout)
        return j

    def list(self) -> list[dict]:
        return [j.public() for j in sorted(self.jobs.values(), key=lambda j: j.created)]
