"""claudebolt command line (ships as claudebolt-engine.exe)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .service import Service, ServiceError

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Local automatic video/audio editor: cuts silences, fillers and retakes.")


def _version(v: bool) -> None:
    if v:
        typer.echo(f"claudebolt {__version__}")
        raise typer.Exit()


@app.callback()
def main(version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True)] = False):
    pass


def _svc() -> Service:
    return Service()


def _die(e: Exception) -> None:
    typer.echo(f"error: {e}", err=True)
    if getattr(e, "hint", None):
        typer.echo(f"hint: {e.hint}", err=True)
    raise typer.Exit(1)


def _open(svc: Service, path: str) -> str:
    if path.endswith(".claudebolt.json"):
        from .timeline import store

        pr = store.load(path)
        return svc.open_media([pr.sources[0].path], project_path=path)["id"]
    return svc.open_media([path])["id"]


def _detect_overrides(threshold, grace, pad, min_keep, speed, mode) -> dict:
    o: dict = {}
    if threshold is not None:
        o["threshold"] = "auto" if threshold == "auto" else float(threshold)
    if grace is not None:
        o["grace"] = grace
    if pad is not None:
        left, right = (float(x) for x in pad.split(","))
        o["pad_left"], o["pad_right"] = left, right
    if min_keep is not None:
        o["min_keep"] = min_keep
    if speed is not None:
        o["silence_action"] = "speed"
        o["speed_rate"] = speed
    if mode is not None:
        o["mode"] = mode
    return o


Thr = Annotated[str | None, typer.Option("--threshold", help="'auto' or dBFS like -35")]
Grace = Annotated[float | None, typer.Option("--grace")]
Pad = Annotated[str | None, typer.Option("--pad", help="left,right seconds, e.g. 0.01,0.15")]
MinKeep = Annotated[float | None, typer.Option("--min-keep")]
Speed = Annotated[float | None, typer.Option("--speed", help="speed up silences instead of cutting")]
Mode = Annotated[str | None, typer.Option("--mode", help="rms | vad | both")]


@app.command()
def detect(input: Path, json_out: Annotated[bool, typer.Option("--json")] = False,
           threshold: Thr = None, grace: Grace = None, pad: Pad = None, min_keep: MinKeep = None,
           speed: Speed = None, mode: Mode = None):
    """Detect silences and print the cut list."""
    svc = _svc()
    try:
        pid = _open(svc, str(input))
        res = svc.detect_silence(pid, _detect_overrides(threshold, grace, pad, min_keep, speed, mode))
        tl = svc.get_timeline(pid, "segments", limit=100000)
    except ServiceError as e:
        _die(e)
    if json_out:
        typer.echo(json.dumps({"summary": {k: v for k, v in res.items() if k != "longest_removes"},
                               "segments": tl["segments"]}, indent=2))
    else:
        typer.echo(f"{res['source_duration']}s -> {res['output_duration']}s "
                   f"({res['percent_removed']}% removed, threshold {res['threshold_db']} dB)")
        for s in tl["segments"]:
            typer.echo(f"  {s['op']:<6} {s['src_start']:>9.3f} - {s['src_end']:>9.3f}")


@app.command()
def cut(input: Path, output: Annotated[Path, typer.Option("-o", "--output")],
        threshold: Thr = None, grace: Grace = None, pad: Pad = None, min_keep: MinKeep = None,
        speed: Speed = None, mode: Mode = None,
        encoder: Annotated[str, typer.Option(help="libx264 | auto | h264_nvenc ...")] = "libx264"):
    """Detect silences and render the edited file (video or audio)."""
    svc = _svc()
    try:
        pid = _open(svc, str(input))
        svc.detect_silence(pid, _detect_overrides(threshold, grace, pad, min_keep, speed, mode))
        job = svc.render(pid, str(output), {"encoder_pref": encoder})
        with typer.progressbar(length=100, label="rendering") as bar:
            last = 0
            while True:
                j = svc.wait_job(job["job_id"], 0.2)
                pct = int(j["progress"] * 100)
                bar.update(pct - last)
                last = pct
                if j["status"] in ("done", "failed", "cancelled"):
                    break
        if j["status"] != "done":
            raise ServiceError(j.get("error", j["status"]))
        typer.echo(f"wrote {j['result']['path']} ({j['result']['duration']:.2f}s)")
    except ServiceError as e:
        _die(e)
    except Exception as e:  # noqa: BLE001
        _die(e)


@app.command()
def export(project: Path, format: Annotated[str, typer.Option("--format")],
           output: Annotated[Path, typer.Option("-o")], keep_all_cuts: bool = False):
    """Export a .claudebolt.json project (fcpxml, xmeml, edl, srt, vtt, audacity, cutlist)."""
    svc = _svc()
    try:
        pid = _open(svc, str(project))
        typer.echo(svc.export(pid, format, str(output), keep_all_cuts)["path"])
    except (ServiceError, ValueError) as e:
        _die(e)


@app.command()
def transcribe(input: Path, model: str = "small.en", language: str | None = None):
    """Transcribe locally with Whisper (downloads the model on first use)."""
    svc = _svc()
    try:
        pid = _open(svc, str(input))
        if not any(m["installed"] for m in svc.list_models() if m["name"] == model):
            typer.echo(f"downloading model {model} ...")
            j = svc.wait_job(svc.download_model(model)["job_id"])
            if j["status"] != "done":
                raise ServiceError(j.get("error", "download failed"))
        j = svc.wait_job(svc.transcribe(pid, model, language)["job_id"])
        if j["status"] != "done":
            raise ServiceError(j.get("error", "transcription failed"))
        svc.save_project(pid)
        typer.echo(json.dumps(j["result"]))
    except ServiceError as e:
        _die(e)


@app.command()
def cleanup(project: Path, apply: Annotated[str | None, typer.Option(
    "--apply", help="e.g. 'filler>=0.8' accepts matching proposals")] = None,
            kinds: str = "filler,false_start,retake"):
    """Find fillers / false starts / retakes in the project's transcript."""
    svc = _svc()
    try:
        pid = _open(svc, str(project))
        res = svc.run_cleanup(pid, kinds.split(","))
        typer.echo(json.dumps(res))
        if apply:
            kind, _, conf = apply.partition(">=")
            r = svc.accept_proposals(pid, selector={"kind": kind or None,
                                                    "min_confidence": float(conf or 0)})
            typer.echo(f"accepted {r['accepted']}; output now {r['output_duration']}s")
        svc.save_project(pid)
    except ServiceError as e:
        _die(e)


models_app = typer.Typer(help="Manage local models.")
app.add_typer(models_app, name="models")


@models_app.command("list")
def models_list():
    for m in _svc().list_models():
        typer.echo(f"{'*' if m['installed'] else ' '} {m['name']:<16} {m['size_mb']:>5} MB  {m['note']}")


@models_app.command("download")
def models_download(name: str):
    svc = _svc()
    j = svc.wait_job(svc.download_model(name)["job_id"])
    typer.echo(j["status"] if j["status"] == "done" else j.get("error"))


@models_app.command("vad")
def models_vad():
    """Download the Silero VAD model (used by --mode vad|both)."""
    from .detect import vad

    typer.echo(str(vad.ensure_model()))


@app.command()
def serve(port: int = 0, host: str = "127.0.0.1"):
    """Start the local engine: REST + WebSocket + MCP over HTTP (prints {port, token})."""
    from .server.app import serve as _serve

    _serve(host, port)


mcp_app = typer.Typer(help="MCP server for AI agents.", invoke_without_command=True)
app.add_typer(mcp_app, name="mcp")


@mcp_app.callback()
def mcp_stdio(ctx: typer.Context):
    """Run the MCP server over stdio (proxies to a running engine when there is one)."""
    if ctx.invoked_subcommand is None:
        from .mcp.stdio import run_stdio

        run_stdio()


@mcp_app.command("install")
def mcp_install(
    agents: Annotated[list[str] | None, typer.Argument(
        help="Agents to register with (default: every detected one). See --list.")] = None,
    list_: Annotated[bool, typer.Option("--list", help="Show supported agents and exit.")] = False,
    claude_code: Annotated[bool, typer.Option("--claude-code", hidden=True)] = False,
    claude_desktop: Annotated[bool, typer.Option("--claude-desktop", hidden=True)] = False,
):
    """Register claudebolt as an MCP server in local AI agents (Claude Code, Codex, OpenCode, ...)."""
    from .mcp.install import install, list_clients

    if list_:
        for c in list_clients():
            typer.echo(f"{'*' if c['detected'] else ' '} {c['id']:<15} {c['label']}")
        typer.echo("(* = detected on this machine)")
        return
    targets = list(agents or []) + ["claude-code"] * claude_code + ["claude-desktop"] * claude_desktop
    try:
        lines = install(targets or None)
    except ValueError as e:
        _die(e)
    for line in lines:
        typer.echo(line)


if __name__ == "__main__":
    sys.exit(app())
