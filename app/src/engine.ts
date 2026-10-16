// Connection to the local engine (REST + WebSocket on 127.0.0.1). No business logic lives here.
import type { EngineEvent } from "./types";

export interface Conn {
  base: string;
  token: string;
}

let conn: Conn | null = null;

const isTauri = () => "__TAURI_INTERNALS__" in window;

/** Resolve the engine address: Tauri command in the app, ?port=&token= (or saved) in a browser. */
export async function connect(timeoutMs = 30000): Promise<Conn> {
  if (conn) return conn;
  const t0 = Date.now();
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    for (;;) {
      const info = await invoke<{ port: number; token: string } | null>("engine_info");
      if (info) {
        conn = { base: `http://127.0.0.1:${info.port}`, token: info.token };
        return conn;
      }
      if (Date.now() - t0 > timeoutMs) throw new Error("engine did not start");
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  const q = new URLSearchParams(location.search);
  let port = q.get("port");
  let token = q.get("token");
  try {
    if (port && token) localStorage.setItem("claudebolt.conn", JSON.stringify({ port, token }));
    else {
      const saved = JSON.parse(localStorage.getItem("claudebolt.conn") ?? "null");
      if (saved) ({ port, token } = saved);
    }
  } catch {
    /* storage unavailable */
  }
  if (!port || !token) throw new Error("open with ?port=<engine port>&token=<token> (see `claudebolt serve`)");
  conn = { base: `http://127.0.0.1:${port}`, token };
  return conn;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public hint?: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const c = await connect();
  const r = await fetch(c.base + "/api" + path, {
    method,
    headers: { Authorization: `Bearer ${c.token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) {
    const d = data?.detail ?? data;
    throw new ApiError(d?.error ?? d?.hint ?? `HTTP ${r.status}`, r.status, d?.hint, d);
  }
  return data as T;
}

export const get = <T>(p: string) => api<T>("GET", p);
export const post = <T>(p: string, b: unknown = {}) => api<T>("POST", p, b);

export function mediaUrl(pid: string, sid: string): string {
  if (!conn) throw new Error("not connected");
  return `${conn.base}/api/projects/${pid}/media/${sid}?token=${encodeURIComponent(conn.token)}`;
}

/** Subscribe to /events with auto-reconnect. Returns an unsubscribe function. */
export function openEvents(onEvent: (e: EngineEvent) => void, onState?: (up: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  const start = async () => {
    try {
      const c = await connect();
      ws = new WebSocket(c.base.replace("http", "ws") + `/events?token=${encodeURIComponent(c.token)}`);
      ws.onopen = () => onState?.(true);
      ws.onmessage = (m) => onEvent(JSON.parse(m.data));
      ws.onclose = () => {
        onState?.(false);
        if (!closed) setTimeout(start, 1000);
      };
    } catch {
      if (!closed) setTimeout(start, 1000);
    }
  };
  void start();
  return () => {
    closed = true;
    ws?.close();
  };
}

export async function pickFiles(): Promise<string[] | null> {
  if (!isTauri()) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({
    multiple: true,
    filters: [{ name: "Media", extensions: ["mp4", "mov", "mkv", "webm", "avi", "m4v", "wav", "mp3", "m4a", "flac", "ogg", "opus", "aac"] }],
  });
  if (!r) return [];
  return Array.isArray(r) ? r : [r];
}

export async function pickSavePath(defaultPath: string): Promise<string | null> {
  if (!isTauri()) return null;
  const { save } = await import("@tauri-apps/plugin-dialog");
  return save({ defaultPath });
}
