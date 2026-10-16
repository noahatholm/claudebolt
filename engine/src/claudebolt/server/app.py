"""Local engine: FastAPI REST + WebSocket events + MCP over streamable HTTP, 127.0.0.1 only."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import __version__
from ..config import daemon_file
from ..mcp.server import build_mcp
from ..service import Service, ServiceError

ALLOWED_ORIGINS = [
    "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
    "http://localhost:1420", "http://127.0.0.1:1420", "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class Guard:
    """Pure-ASGI guard: Host allow-list (DNS-rebinding), Origin allow-list, bearer token."""

    def __init__(self, app: ASGIApp, token: str | None):
        self.app, self.token = app, token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        host = headers.get("host", "").rsplit(":", 1)[0].strip("[]")
        origin = headers.get("origin")
        ok = host in ("127.0.0.1", "localhost", "::1", "testserver")
        if origin and origin not in ALLOWED_ORIGINS:
            ok = False
        if scope["type"] == "http" and scope["method"] == "OPTIONS" and ok:
            return await self.app(scope, receive, send)  # CORS preflight carries no token
        if ok and self.token:
            got = headers.get("authorization", "")
            if got.startswith("Bearer "):
                got = got[7:]
            else:
                q = parse_qs(scope.get("query_string", b"").decode())
                got = (q.get("token") or [""])[0]
            ok = secrets.compare_digest(got, self.token)
        if ok:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            resp = JSONResponse({"error": "forbidden"}, status_code=403)
            await resp(scope, receive, send)


class OpenBody(BaseModel):
    paths: list[str]
    project_path: str | None = None


class DetectBody(BaseModel):
    settings: dict | None = None


class EditsBody(BaseModel):
    ops: list[dict]
    expected_version: int | None = None
    actor: str = "user"
    time_base: str = "source"


class StepBody(BaseModel):
    steps: int = 1


class TranscribeBody(BaseModel):
    model: str | None = None
    language: str | None = None


class CleanupBody(BaseModel):
    kinds: list[str] | None = None
    fillers: list[str] | None = None
    min_confidence: float | None = None


class ProposalBody(BaseModel):
    ids: list[str] | None = None
    kind: str | None = None
    min_confidence: float | None = None


class RenderBody(BaseModel):
    output_path: str | None = None
    settings: dict | None = None


class PreviewBody(BaseModel):
    start: float
    end: float
    time_base: str = "source"


class ExportBody(BaseModel):
    format: str
    path: str | None = None
    keep_all_cuts: bool = False


def create_app(svc: Service, token: str | None = None, with_mcp: bool = True) -> FastAPI:
    mcp = build_mcp(svc, streamable_http_path="/mcp") if with_mcp else None

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with contextlib.AsyncExitStack() as stack:
            if mcp is not None:
                await stack.enter_async_context(mcp.session_manager.run())
            yield
        svc.flush()

    app = FastAPI(title="claudebolt engine", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.exception_handler(ServiceError)
    async def _svc_err(_: Request, e: ServiceError):
        return JSONResponse({"error": str(e), "hint": e.hint}, status_code=400)

    @app.exception_handler(ValueError)
    async def _val_err(_: Request, e: ValueError):
        return JSONResponse({"error": str(e)}, status_code=400)

    api = "/api"

    @app.get(f"{api}/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    # projects
    @app.post(f"{api}/projects")
    def open_project(b: OpenBody) -> dict:
        return svc.open_media(b.paths, b.project_path)

    @app.get(f"{api}/projects")
    def projects() -> list[dict]:
        return svc.list_projects()

    @app.get(api + "/projects/{pid}")
    def get_project(pid: str) -> dict:
        return svc.describe(pid)

    @app.get(api + "/projects/{pid}/full")
    def get_full(pid: str) -> Any:
        return json.loads(svc.project(pid).model_dump_json(exclude={"transcript": {"words"}}))

    @app.delete(api + "/projects/{pid}")
    def close(pid: str) -> dict:
        return svc.close_project(pid)

    @app.post(api + "/projects/{pid}/save")
    def save(pid: str) -> dict:
        return {"path": svc.save_project(pid)}

    # analysis
    @app.get(api + "/projects/{pid}/analyze")
    def analyze(pid: str, track: int = 0) -> dict:
        return svc.analyze_audio(pid, track)

    @app.get(api + "/projects/{pid}/levels")
    def levels(pid: str, start: float = 0.0, end: float | None = None, resolution: int = 200) -> dict:
        return svc.get_levels(pid, start, end, resolution)

    @app.get(api + "/projects/{pid}/peaks")
    def peaks(pid: str, px: int = 2000) -> dict:
        return svc.get_peaks(pid, px)

    @app.post(api + "/projects/{pid}/tracks/{track}")
    def set_track(pid: str, track: int, patch: dict) -> dict:
        return svc.set_track(pid, track, patch.get("offset"), patch.get("muted"))

    @app.post(api + "/projects/{pid}/sync")
    def sync(pid: str) -> dict:
        return svc.auto_sync(pid)

    @app.post(api + "/projects/{pid}/detect")
    def detect(pid: str, b: DetectBody) -> dict:
        return svc.detect_silence(pid, b.settings)

    # timeline
    @app.get(api + "/projects/{pid}/timeline")
    def timeline(pid: str, detail: str = "segments", cursor: int = 0, limit: int = 100000,
                 start: float | None = None, end: float | None = None,
                 time_base: str = "source") -> dict:
        rng = (start, end) if start is not None and end is not None else None
        return svc.get_timeline(pid, detail, rng, cursor, limit, time_base)

    @app.post(api + "/projects/{pid}/edits")
    def edits(pid: str, b: EditsBody) -> dict:
        r = svc.apply_edits(pid, b.ops, b.expected_version, b.actor, b.time_base)
        if r.get("conflict"):
            raise HTTPException(409, r)
        return r

    @app.post(api + "/projects/{pid}/undo")
    def undo(pid: str, b: StepBody) -> dict:
        return svc.undo(pid, b.steps)

    @app.post(api + "/projects/{pid}/redo")
    def redo(pid: str, b: StepBody) -> dict:
        return svc.redo(pid, b.steps)

    @app.get(api + "/projects/{pid}/map_time")
    def map_time(pid: str, t: float, from_: str = "source") -> dict:
        return svc.map_time(pid, t, from_)

    # transcript + cleanup
    @app.post(api + "/projects/{pid}/transcribe")
    def transcribe(pid: str, b: TranscribeBody) -> dict:
        return svc.transcribe(pid, b.model, b.language)

    @app.get(api + "/projects/{pid}/transcript")
    def transcript(pid: str, start: float | None = None, end: float | None = None,
                   cursor: int = 0, limit: int = 100000) -> dict:
        return svc.get_transcript(pid, start, end, cursor, limit)

    @app.get(api + "/projects/{pid}/search")
    def search(pid: str, q: str, regex: bool = False) -> dict:
        return svc.search_transcript(pid, q, regex)

    @app.post(api + "/projects/{pid}/cleanup")
    def cleanup(pid: str, b: CleanupBody) -> dict:
        return svc.run_cleanup(pid, b.kinds, b.fillers, b.min_confidence)

    @app.get(api + "/projects/{pid}/proposals")
    def proposals(pid: str, kind: str | None = None, status: str | None = None,
                  cursor: int = 0, limit: int = 100000) -> dict:
        return svc.list_proposals(pid, kind, status, cursor, limit)

    @app.post(api + "/projects/{pid}/proposals/accept")
    def accept(pid: str, b: ProposalBody) -> dict:
        sel = None if b.ids else {"kind": b.kind, "min_confidence": b.min_confidence or 0.0}
        return svc.accept_proposals(pid, b.ids, sel)

    @app.post(api + "/projects/{pid}/proposals/reject")
    def reject(pid: str, b: ProposalBody) -> dict:
        sel = None if b.ids else {"kind": b.kind, "min_confidence": b.min_confidence or 0.0}
        return svc.reject_proposals(pid, b.ids, sel)

    # output
    @app.post(api + "/projects/{pid}/render")
    def render(pid: str, b: RenderBody) -> dict:
        return svc.render(pid, b.output_path, b.settings)

    @app.post(api + "/projects/{pid}/preview")
    def preview(pid: str, b: PreviewBody) -> dict:
        return svc.preview_clip(pid, b.start, b.end, b.time_base)

    @app.post(api + "/projects/{pid}/export")
    def export(pid: str, b: ExportBody) -> dict:
        return svc.export(pid, b.format, b.path, b.keep_all_cuts)

    @app.get(api + "/projects/{pid}/media/{sid}")
    def media(pid: str, sid: str):
        """Source media for playback (Range supported); token may be passed as ?token=."""
        src = next((s for s in svc.project(pid).sources if s.id == sid), None)
        if src is None:
            raise HTTPException(404, "no such source")
        return FileResponse(src.path)

    # settings / models / jobs
    @app.get(f"{api}/settings")
    def get_settings() -> dict:
        return svc.get_settings()

    @app.patch(f"{api}/settings")
    def patch_settings(patch: dict) -> dict:
        return svc.update_settings(patch)

    @app.get(f"{api}/models")
    def models() -> list[dict]:
        return svc.list_models()

    @app.post(api + "/models/{name}/download")
    def download(name: str) -> dict:
        return svc.download_model(name)

    @app.get(f"{api}/jobs")
    def jobs() -> list[dict]:
        return svc.list_jobs()

    @app.get(api + "/jobs/{jid}")
    def job(jid: str) -> dict:
        return svc.get_job(jid)

    @app.post(api + "/jobs/{jid}/cancel")
    def cancel(jid: str) -> dict:
        return svc.cancel_job(jid)

    @app.websocket("/events")
    async def events(ws: WebSocket) -> None:
        await ws.accept()
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[dict] = asyncio.Queue()
        unsub = svc.bus.subscribe(lambda e: loop.call_soon_threadsafe(q.put_nowait, e))
        try:
            while True:
                await ws.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            unsub()

    if mcp is not None:
        app.mount("/", mcp.streamable_http_app())  # serves /mcp; mounted last

    return Guard(app, token)  # type: ignore[return-value]


def serve(host: str = "127.0.0.1", port: int = 0) -> None:
    """Bind, announce {port, token} on stdout, write daemon.json, and run until killed."""
    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("claudebolt only binds to loopback addresses")
    token = secrets.token_urlsafe(24)
    svc = Service(sandbox=True)
    app = create_app(svc, token)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, port))
    real_port = sock.getsockname()[1]
    info = {"port": real_port, "token": token, "pid": os.getpid()}
    df = daemon_file()
    df.write_text(json.dumps(info), "utf-8")
    try:
        os.chmod(df, 0o600)
    except OSError:
        pass
    print(json.dumps({"port": real_port, "token": token}), flush=True)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    try:
        server.run(sockets=[sock])
    finally:
        svc.flush()
        with contextlib.suppress(OSError):
            Path(df).unlink()
        sys.stdout.flush()
