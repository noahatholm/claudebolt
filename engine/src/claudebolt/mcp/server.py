"""MCP server: tools, resources and prompts over the shared service layer."""

from __future__ import annotations

import functools
import json
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP

from ..service import Service, ServiceError

INSTRUCTIONS = """\
claudebolt edits video and audio files locally: it removes silences, filler words, false starts
and retakes. Typical flow: open_media -> analyze_audio -> detect_silence -> transcribe (needs a
downloaded model, see list_models/download_model) -> run_cleanup -> list_proposals ->
accept_proposals/reject_proposals -> preview_clip (to check a section) -> render or export.
Times are seconds. Segments report both source (src_*) and edited-output (out_*) times.
Long operations return {job_id}; poll get_job until status is done/failed.
Use expected_version with apply_edits so you never overwrite a human's concurrent edit.
"""


def _tool(mcp: FastMCP, **kw: Any):
    """Register a sync service call as an async tool: runs in a worker thread, errors -> {error, hint}."""

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*a, **k):
            try:
                return await anyio.to_thread.run_sync(functools.partial(fn, *a, **k))
            except ServiceError as e:
                return {"error": str(e), "hint": e.hint}
            except (ValueError, FileNotFoundError, KeyError) as e:
                return {"error": str(e), "hint": "check the arguments"}

        mcp.tool(**kw)(wrapper)
        return fn

    return deco


def build_mcp(svc: Service, **kw: Any) -> FastMCP:
    mcp = FastMCP("claudebolt", instructions=INSTRUCTIONS, **kw)
    tool = functools.partial(_tool, mcp)

    # ---- projects
    @tool()
    def open_media(paths: list[str], project_path: str | None = None) -> dict:
        """Open one or more media files (video or audio) as a project. The first is the primary
        track; extra files become aux tracks (multitrack). Re-opens an existing project file if found."""
        return svc.open_media(paths, project_path)

    @tool()
    def list_projects() -> list[dict]:
        """List open projects."""
        return svc.list_projects()

    @tool()
    def get_project(project_id: str) -> dict:
        """Project metadata: sources, durations, version, whether a transcript exists."""
        return svc.describe(project_id)

    @tool()
    def save_project(project_id: str, path: str | None = None) -> dict:
        """Save the project file (<media>.claudebolt.json by default)."""
        return {"path": svc.save_project(project_id, path)}

    @tool()
    def close_project(project_id: str) -> dict:
        """Save and close a project."""
        return svc.close_project(project_id)

    # ---- analysis / detection
    @tool()
    def analyze_audio(project_id: str, track: int = 0) -> dict:
        """Loudness analysis: suggested threshold (dBFS), floor/speech levels, histogram, warnings."""
        return svc.analyze_audio(project_id, track)

    @tool()
    def detect_silence(project_id: str, settings: dict | None = None) -> dict:
        """Detect silences and rebuild the timeline (locked/manual/agent edits are preserved).
        settings overrides: mode(rms|vad|both), threshold(dB or 'auto'), grace, pad_left, pad_right,
        min_keep, silence_action(cut|speed), speed_rate, keep_edges. Returns a timeline summary."""
        return svc.detect_silence(project_id, settings, actor="agent")

    @tool()
    def get_levels(project_id: str, start: float = 0.0, end: float | None = None,
                   resolution: int = 200) -> dict:
        """dB level series (<= 500 points) over a source-time range, for 'is this quiet?' questions."""
        return svc.get_levels(project_id, start, end, resolution)

    @tool()
    def sync_tracks(project_id: str) -> dict:
        """Multitrack: estimate aux track offsets against the primary by cross-correlation."""
        return svc.auto_sync(project_id)

    @tool()
    def set_track(project_id: str, track: int, offset: float | None = None,
                  muted: bool | None = None) -> dict:
        """Set a track's offset (seconds) or mute flag."""
        return svc.set_track(project_id, track, offset, muted)

    # ---- models / transcript
    @tool()
    def list_models() -> list[dict]:
        """Whisper models with sizes and whether each is installed."""
        return svc.list_models()

    @tool()
    def download_model(name: str) -> dict:
        """Download a Whisper model (job). Needed once before transcribe."""
        return svc.download_model(name)

    @tool()
    def transcribe(project_id: str, model: str | None = None, language: str | None = None) -> dict:
        """Transcribe locally with word timestamps (job). Cached per audio + model."""
        return svc.transcribe(project_id, model, language)

    @tool()
    def get_transcript(project_id: str, start: float | None = None, end: float | None = None,
                       cursor: int = 0, include_proposals: bool = True) -> dict:
        """Words with index, times and removed flag (paged by cursor); proposals inline."""
        return svc.get_transcript(project_id, start, end, cursor, 500, include_proposals)

    @tool()
    def search_transcript(project_id: str, query: str, regex: bool = False) -> dict:
        """Find text in the transcript; returns word ranges and times usable with apply_edits."""
        return svc.search_transcript(project_id, query, regex)

    # ---- cleanup / proposals
    @tool()
    def run_cleanup(project_id: str, kinds: list[str] | None = None, fillers: list[str] | None = None,
                    min_confidence: float | None = None) -> dict:
        """Find fillers, false_starts and retakes in the transcript. Creates pending proposals."""
        return svc.run_cleanup(project_id, kinds, fillers, min_confidence)

    @tool()
    def list_proposals(project_id: str, kind: str | None = None, status: str | None = None,
                       cursor: int = 0) -> dict:
        """Proposals with text, confidence and +-5 words of context."""
        return svc.list_proposals(project_id, kind, status, cursor)

    @tool()
    def accept_proposals(project_id: str, ids: list[str] | None = None,
                         kind: str | None = None, min_confidence: float | None = None) -> dict:
        """Accept proposals by ids, or all pending of a kind above a confidence. Applies the cuts."""
        sel = None if ids else {"kind": kind, "min_confidence": min_confidence or 0.0}
        return svc.accept_proposals(project_id, ids, sel, actor="agent")

    @tool()
    def reject_proposals(project_id: str, ids: list[str] | None = None,
                         kind: str | None = None, min_confidence: float | None = None) -> dict:
        """Reject proposals by ids, or all pending of a kind above a confidence."""
        sel = None if ids else {"kind": kind, "min_confidence": min_confidence or 0.0}
        return svc.reject_proposals(project_id, ids, sel, actor="agent")

    # ---- timeline
    @tool()
    def get_timeline(project_id: str, detail: str = "summary", start: float | None = None,
                     end: float | None = None, cursor: int = 0, time_base: str = "source") -> dict:
        """detail='summary' (totals, counts by reason, 20 longest removes) or 'segments' (paged)."""
        rng = (start, end) if start is not None and end is not None else None
        return svc.get_timeline(project_id, detail, rng, cursor, 200, time_base)

    @tool()
    def apply_edits(project_id: str, ops: list[dict], expected_version: int | None = None,
                    time_base: str = "source") -> dict:
        """Apply edits atomically. Each op: {action: keep|remove|speed|zoom|lock|unlock,
        start, end} or {action: keep|remove, word_range: [a, b]}, plus speed/zoom where relevant.
        On a version mismatch returns {conflict: true, version}."""
        return svc.apply_edits(project_id, ops, expected_version, "agent", time_base)

    @tool()
    def undo(project_id: str, steps: int = 1) -> dict:
        """Undo the last edits."""
        return svc.undo(project_id, steps, "agent")

    @tool()
    def redo(project_id: str, steps: int = 1) -> dict:
        """Redo undone edits."""
        return svc.redo(project_id, steps, "agent")

    @tool()
    def map_time(project_id: str, t: float, from_: str = "source") -> dict:
        """Convert a time between source and edited-output time (from_='source'|'output')."""
        return svc.map_time(project_id, t, from_)

    # ---- output
    @tool()
    def preview_clip(project_id: str, start: float, end: float, time_base: str = "source") -> dict:
        """Render a short low-res preview of the edited result for a range; returns a file path."""
        return svc.preview_clip(project_id, start, end, time_base)

    @tool()
    def render(project_id: str, output_path: str | None = None, settings: dict | None = None) -> dict:
        """Render the edited video/audio (job). Output extension picks the format (mp4, mp3, wav, ...).
        settings: crf, encoder_pref(libx264|auto|h264_nvenc), fade_ms, zoom_mode, zoom."""
        return svc.render(project_id, output_path, settings)

    @tool()
    def export(project_id: str, format: str, path: str | None = None,
               keep_all_cuts: bool = False) -> dict:
        """Export fcpxml | xmeml | edl | srt | vtt | audacity | cutlist."""
        return svc.export(project_id, format, path, keep_all_cuts)

    # ---- jobs
    @tool()
    def get_job(job_id: str) -> dict:
        """Status, progress and result of a job."""
        return svc.get_job(job_id)

    @tool()
    def cancel_job(job_id: str) -> dict:
        """Cancel a running job."""
        return svc.cancel_job(job_id)

    @tool()
    def list_jobs() -> list[dict]:
        """All jobs in this session."""
        return svc.list_jobs()

    # ---- resources
    @mcp.resource("claudebolt://settings")
    def settings_resource() -> str:
        return json.dumps(svc.get_settings(), indent=2)

    @mcp.resource("claudebolt://project/{project_id}")
    def project_resource(project_id: str) -> str:
        return json.dumps(svc.get_timeline(project_id, "summary"), indent=2)

    @mcp.resource("claudebolt://project/{project_id}/transcript")
    def transcript_resource(project_id: str) -> str:
        p = svc.project(project_id)
        if p.transcript is None:
            return "(no transcript yet: call transcribe)"
        lines, cur, mark = [], [], -1
        for w in p.transcript.words:
            m = int(w.start // 15)
            if m != mark:
                if cur:
                    lines.append(" ".join(cur))
                    cur = []
                mark = m
                cur.append(f"[{int(w.start // 60):02d}:{int(w.start % 60):02d}]")
            cur.append(w.text.strip())
        lines.append(" ".join(cur))
        return "\n".join(lines)

    # ---- prompts (agent playbooks)
    @mcp.prompt()
    def tighten_podcast(path: str) -> str:
        """Tighten a podcast: pauses and filler words."""
        return (f"Open {path} with open_media, call analyze_audio, then detect_silence with "
                "grace 0.6. Download a model if needed and transcribe. Run run_cleanup for fillers, "
                "accept proposals with confidence >= 0.8, review the lower-confidence ones with "
                "list_proposals (use the context) and accept or reject each. Check a few cuts with "
                "preview_clip, then render to an audio file next to the source.")

    @mcp.prompt()
    def clean_talking_head(path: str) -> str:
        """Clean a talking-head video: pauses, fillers, retakes, punch-zoom."""
        return (f"Open {path}. detect_silence with mode 'both' if VAD is available, otherwise rms. "
                "Transcribe, run_cleanup for all kinds, accept false starts and fillers >= 0.8, review "
                "retakes by reading both takes and keeping the better one. Use apply_edits zoom on "
                "alternate kept sections to hide jump cuts. Render the mp4 and export an fcpxml.")

    @mcp.prompt()
    def remove_retakes(path: str) -> str:
        """Find and resolve retakes using the transcript."""
        return (f"Open {path} and transcribe it. Run run_cleanup with kinds ['retake']. For each "
                "proposal read the text and its context, decide whether the earlier take should go, "
                "then accept_proposals or reject_proposals. Preview the result with preview_clip.")

    return mcp
