import asyncio
import json
import os
import subprocess
import sys
import time

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from claudebolt.mcp.server import build_mcp
from claudebolt.server.app import create_app
from claudebolt.service import Service
from claudebolt.timeline.model import Word
from claudebolt.transcribe.sentences import build

TOKEN = "t0k3n"
H = {"Authorization": f"Bearer {TOKEN}"}


def client(svc):
    app = create_app(svc, TOKEN, with_mcp=False)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:1")


async def test_rest_flow_and_auth(media):
    svc = Service(sandbox=True)
    async with client(svc) as c:
        assert (await c.get("/api/health")).status_code == 403  # no token
        assert (await c.get("/api/health", headers=H | {"Origin": "http://evil.example"})).status_code == 403
        assert (await c.get("/api/health", headers=H | {"Host": "evil.example"})).status_code == 403
        assert (await c.get("/api/health?token=" + TOKEN)).status_code == 200
        r = await c.post("/api/projects", json={"paths": [str(media / "pattern.wav")]}, headers=H)
        pid = r.json()["id"]
        d = await c.post(f"/api/projects/{pid}/detect", json={}, headers=H)
        assert d.json()["percent_removed"] > 40
        pk = (await c.get(f"/api/projects/{pid}/peaks?px=100", headers=H)).json()
        assert len(pk["peaks"]) == 100
        v = d.json()["version"]
        ok = await c.post(f"/api/projects/{pid}/edits", headers=H,
                          json={"ops": [{"action": "remove", "start": 0, "end": 0.5}],
                                "expected_version": v})
        assert ok.status_code == 200
        stale = await c.post(f"/api/projects/{pid}/edits", headers=H,
                             json={"ops": [{"action": "remove", "start": 1, "end": 1.1}],
                                   "expected_version": v})
        assert stale.status_code == 409
        bad = await c.post(f"/api/projects/{pid}/export", headers=H,
                           json={"format": "edl", "path": "C:/Windows/x.edl"})
        assert bad.status_code == 400 and "hint" in bad.json()
        u = await c.post(f"/api/projects/{pid}/undo", json={}, headers=H)
        assert u.json()["applied"]
        out = str(media / "api.wav")
        j = (await c.post(f"/api/projects/{pid}/render", json={"output_path": out}, headers=H)).json()
        for _ in range(100):
            st = (await c.get(f"/api/jobs/{j['job_id']}", headers=H)).json()
            if st["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.1)
        assert st["status"] == "done"


async def test_errors_carry_cors_headers(media):
    svc = Service(sandbox=True)
    origin = {"Origin": "http://tauri.localhost"}
    app = create_app(svc, TOKEN, with_mcp=False)
    t = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=t, base_url="http://127.0.0.1:1") as c:
        denied = await c.get("/api/health", headers=origin)
        assert denied.status_code == 403
        assert denied.headers["access-control-allow-origin"] == "http://tauri.localhost"
        pid = (await c.post("/api/projects", json={"paths": [str(media / "pattern.wav")]},
                            headers=H)).json()["id"]
        svc.get_peaks = lambda *a, **k: 1 / 0
        crash = await c.get(f"/api/projects/{pid}/peaks", headers=H | origin)
        assert crash.status_code == 500
        assert crash.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_concurrent_analysis_decodes_once(media, monkeypatch):
    import threading

    from claudebolt import service as service_mod

    svc = Service()
    pid = svc.open_media([str(media / "pattern.wav")])["id"]
    real, calls = service_mod.decode, []

    def slow_decode(*a, **k):
        calls.append(1)
        time.sleep(0.2)
        return real(*a, **k)

    monkeypatch.setattr(service_mod, "decode", slow_decode)
    svc._analyses.clear()
    errors = []

    def peaks():
        try:
            svc.get_peaks(pid, 100)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=peaks) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors and len(calls) == 1


async def test_events_published_on_edit(media):
    svc = Service()
    got = []
    svc.bus.subscribe(got.append)
    pid = svc.open_media([str(media / "pattern.wav")])["id"]
    svc.detect_silence(pid)
    svc.apply_edits(pid, [{"action": "remove", "start": 0, "end": 0.2}], actor="agent")
    ev = [e for e in got if e["type"] == "timeline.changed"]
    assert [e["actor"] for e in ev] == ["user", "agent"] and ev[1]["version"] == ev[0]["version"] + 1


async def test_mcp_end_to_end(media):
    svc = Service(sandbox=True)
    mcp = build_mcp(svc)

    async with create_connected_server_and_client_session(mcp._mcp_server) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"open_media", "detect_silence", "transcribe", "run_cleanup", "accept_proposals",
                "apply_edits", "render", "export", "get_job", "preview_clip"} <= names

        async def call(name, **args):
            r = await c.call_tool(name, args)
            return json.loads(r.content[0].text)

        opened = await call("open_media", paths=[str(media / "pattern.mp3")])
        pid = opened["id"]
        a = await call("analyze_audio", project_id=pid)
        assert "suggested_threshold" in a
        s = await call("detect_silence", project_id=pid, settings={"threshold": "auto"})
        assert s["output_duration"] < s["source_duration"]
        # inject a transcript (whisper needs a model download; covered by the slow test)
        svc.set_transcript(pid, build([Word(text="Hello", start=0.1, end=0.4),
                                       Word(text="um", start=0.5, end=0.8),
                                       Word(text="world.", start=0.9, end=1.1)], "t", "en"))
        cl = await call("run_cleanup", project_id=pid, kinds=["filler"])
        assert cl["created"] == {"filler": 1}
        before = (await call("get_timeline", project_id=pid))["output_duration"]
        acc = await call("accept_proposals", project_id=pid, kind="filler", min_confidence=0.8)
        assert acc["output_duration"] < before
        err = await call("transcribe", project_id=pid, model="nope")
        assert "error" in err and "hint" in err
        conflict = await call("apply_edits", project_id=pid, expected_version=0,
                              ops=[{"action": "remove", "start": 1, "end": 2}])
        assert conflict["conflict"] is True
        out = str(media / "agent.mp3")
        job = await call("render", project_id=pid, output_path=out)
        for _ in range(100):
            st = await call("get_job", job_id=job["job_id"])
            if st["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.1)
        assert st["status"] == "done"
        assert st["result"]["duration"] == pytest.approx(svc.project(pid).output_duration, abs=0.06)
        blocked = await call("render", project_id=pid, output_path="C:/Windows/agent.mp3")
        assert "error" in blocked
        res = await c.read_resource(f"claudebolt://project/{pid}")
        assert "output_duration" in res.contents[0].text
        prompts = {p.name for p in (await c.list_prompts()).prompts}
        assert "tighten_podcast" in prompts


@pytest.fixture
def engine(media):
    env = os.environ | {"CLAUDEBOLT_CACHE": str(media.parent / "ecache")}
    p = subprocess.Popen([sys.executable, "-m", "claudebolt", "serve", "--port", "0"],
                         stdout=subprocess.PIPE, text=True, env=env)
    info = json.loads(p.stdout.readline())
    yield info, env
    p.terminate()
    p.wait(10)


def test_serve_prints_port_token_and_mcp_over_http(engine, media):
    info, env = engine
    base = f"http://127.0.0.1:{info['port']}"
    h = {"Authorization": f"Bearer {info['token']}"}
    assert httpx.get(base + "/api/health").status_code == 403
    assert httpx.get(base + "/api/health", headers=h).json()["ok"] is True
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"}}}
    r = httpx.post(base + "/mcp", json=init, headers=h | {
        "Accept": "application/json, text/event-stream"})
    assert r.status_code == 200 and "claudebolt" in r.text
    assert httpx.get(base + "/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 403
    from websockets.sync.client import connect as ws_connect

    url = f"ws://127.0.0.1:{info['port']}/events?token={info['token']}"
    with ws_connect(url, origin="http://tauri.localhost", open_timeout=10) as ws:
        ws.ping().wait(5)


def test_stdio_proxy_shares_state_with_running_engine(engine, media):
    info, env = engine
    base = f"http://127.0.0.1:{info['port']}"
    h = {"Authorization": f"Bearer {info['token']}"}
    proc = subprocess.Popen([sys.executable, "-m", "claudebolt", "mcp"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env=env)

    def rpc(msg, expect=True):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline()) if expect else None

    try:
        rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"}}})
        rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect=False)
        r = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "open_media", "arguments": {"paths": [str(media / "pattern.wav")]}}})
        opened = json.loads(r["result"]["content"][0]["text"])
        time.sleep(0.2)
        listed = httpx.get(base + "/api/projects", headers=h).json()
        assert [p["id"] for p in listed] == [opened["id"]]  # the UI sees what the agent opened
    finally:
        proc.stdin.close()
        proc.terminate()
