"""`claudebolt mcp`: stdio MCP. Proxies to a running engine, else runs in-process (headless)."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

from ..config import daemon_file


def live_engine() -> tuple[str, str] | None:
    """(base_url, token) of a running engine, or None."""
    try:
        info = json.loads(daemon_file().read_text("utf-8"))
        base = f"http://127.0.0.1:{info['port']}"
        r = httpx.get(f"{base}/api/health", headers={"Authorization": f"Bearer {info['token']}"},
                      timeout=1.5)
        if r.status_code == 200:
            return base, info["token"]
    except Exception:
        return None
    return None


def run_stdio() -> None:
    eng = live_engine()
    if eng:
        proxy(*eng)
        return
    from ..service import Service
    from .server import build_mcp

    svc = Service(sandbox=True)
    try:
        build_mcp(svc).run("stdio")
    finally:
        svc.flush()


def _sse_messages(resp: httpx.Response):
    data: list[str] = []
    for line in resp.iter_lines():
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            yield "\n".join(data)
            data = []
    if data:
        yield "\n".join(data)


def proxy(base: str, token: str) -> None:
    """Bridge newline-delimited JSON-RPC on stdio to the engine's streamable HTTP endpoint."""
    client = httpx.Client(timeout=None)
    state = {"session": None, "protocol": None}
    out_lock = threading.Lock()

    def emit(text: str) -> None:
        with out_lock:
            sys.stdout.write(text.strip() + "\n")
            sys.stdout.flush()

    def forward(line: str) -> None:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if state["session"]:
            headers["mcp-session-id"] = state["session"]
        if state["protocol"]:
            headers["mcp-protocol-version"] = state["protocol"]
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        try:
            with client.stream("POST", f"{base}/mcp", content=line, headers=headers) as r:
                sid = r.headers.get("mcp-session-id")
                if sid:
                    state["session"] = sid
                if r.status_code == 202 or "id" not in msg:
                    r.read()
                    return
                if r.status_code >= 400:
                    r.read()
                    emit(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "error": {
                        "code": -32000, "message": f"engine returned {r.status_code}"}}))
                    return
                ctype = r.headers.get("content-type", "")
                if "text/event-stream" in ctype:
                    for m in _sse_messages(r):
                        emit(m)
                else:
                    emit(r.read().decode())
                if msg.get("method") == "initialize":
                    state["protocol"] = (msg.get("params") or {}).get("protocolVersion")
        except httpx.HTTPError as e:
            emit(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "error": {
                "code": -32000, "message": f"engine unreachable: {e}"}}))

    with ThreadPoolExecutor(8) as pool:
        first = True
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if first:  # initialize must complete before later calls need its session id
                forward(line)
                first = False
            else:
                pool.submit(forward, line)
