"""Locate ffmpeg/ffprobe and run them with progress + cancel."""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def _find(name: str) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    env = os.environ.get("CLAUDEBOLT_FFMPEG")
    if env:
        p = Path(env)
        if p.is_dir():
            p = p / exe
        elif name == "ffprobe":
            p = p.with_name(p.name.replace("ffmpeg", "ffprobe"))
        if p.exists():
            return str(p)
    here = Path(sys.executable).parent
    base = Path(getattr(sys, "_MEIPASS", here))
    for cand in (here / exe, base / exe, base / "bin" / exe):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if not found:
        raise FFmpegError(
            f"{name} not found. Install ffmpeg or set CLAUDEBOLT_FFMPEG to its path."
        )
    return found


def ffmpeg_path() -> str:
    return _find("ffmpeg")


def ffprobe_path() -> str:
    return _find("ffprobe")


@functools.lru_cache(maxsize=1)
def filter_script_flag() -> str:
    """`-/filter_complex` replaced `-filter_complex_script` in FFmpeg 7+."""
    out = subprocess.run([ffmpeg_path(), "-version"], capture_output=True, text=True,
                         creationflags=_NOWIN).stdout
    m = re.search(r"version\s+n?(\d+)", out)
    if m and int(m.group(1)) >= 7:
        return "-/filter_complex"
    if m is None and "N-" in out:  # git builds: assume new
        return "-/filter_complex"
    return "-filter_complex_script"


def run(
    args: list[str],
    *,
    total: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Run ffmpeg with `-progress pipe:1`; progress is a 0..1 fraction of `total` seconds."""
    cmd = [ffmpeg_path(), "-y", "-nostdin", "-hide_banner", "-v", "error",
           "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NOWIN, text=True
    )
    err: list[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        err.append(proc.stderr.read())

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                proc.wait()
                raise Cancelled()
            if on_progress and total and line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                on_progress(max(0.0, min(1.0, us / 1e6 / total)))
        rc = proc.wait()
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        raise
    t.join(timeout=2)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if rc != 0:
        raise FFmpegError(f"ffmpeg failed ({rc}): {(err[0] if err else '').strip()[-2000:]}")
    if on_progress:
        on_progress(1.0)
