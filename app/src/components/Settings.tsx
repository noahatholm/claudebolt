import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { get, isTauri, post } from "../engine";
import { useStore } from "../store";
import { updatesEnabled, useUpdate } from "../updater";

interface Model { name: string; size_mb: number; note: string; installed: boolean }
interface Agent { id: string; label: string; detected: boolean }

export function Settings({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const setError = useStore((s) => s.setError);
  const models = useQuery({ queryKey: ["models"], queryFn: () => get<Model[]>("/models") });
  const agents = useQuery({ queryKey: ["mcp-clients"], queryFn: () => get<Agent[]>("/mcp/clients") });
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const chosen = picked ?? new Set(agents.data?.filter((a) => a.detected).map((a) => a.id));
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (!next.delete(id)) next.add(id);
    setPicked(next);
  };
  const [mcp, setMcp] = useState("");
  const update = useUpdate();
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const [canUpdate, setCanUpdate] = useState(false);
  useEffect(() => {
    if (!isTauri()) return;
    void import("@tauri-apps/api/app").then((m) => m.getVersion()).then(setAppVersion);
    void updatesEnabled().then(setCanUpdate);
  }, []);
  const updateText: Record<string, string> = {
    checking: "Checking...",
    none: "You have the latest version.",
    available: `v${update.version} is available (see the banner at the top).`,
    installing: `Installing v${update.version}...`,
    error: `Update check failed: ${update.error}`,
  };

  const download = async (name: string) => {
    try {
      await post(`/models/${name}/download`);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["models"] }), 3000);
    } catch (e) {
      setError(e);
    }
  };
  const install = async () => {
    try {
      const r = await post<{ lines: string[] }>("/mcp/install", { targets: [...chosen] });
      setMcp(r.lines.join("\n"));
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div className="modal" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h3>Speech models (local Whisper)</h3>
        <table>
          <tbody>
            {models.data?.map((m) => (
              <tr key={m.name}>
                <td>{m.name}</td>
                <td className="muted">{m.size_mb} MB, {m.note}</td>
                <td>{m.installed ? "installed" : <button onClick={() => download(m.name)}>Download</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3>AI agents (MCP)</h3>
        <p className="muted small">Lets AI agents use claudebolt to edit your files. Runs locally.</p>
        {agents.data?.map((a) => (
          <label key={a.id} className="check small">
            <input type="checkbox" checked={chosen.has(a.id)} onChange={() => toggle(a.id)} /> {a.label}
            {!a.detected && <span className="muted"> (not detected)</span>}
          </label>
        ))}
        <button onClick={install} disabled={chosen.size === 0}>Install in selected agents</button>
        {mcp && <pre>{mcp}</pre>}
        {appVersion && (
          <>
            <h3>Updates</h3>
            <p className="muted small">
              claudebolt v{appVersion}.{" "}
              {canUpdate ? updateText[update.status] ?? "" : "Built from source: automatic updates are off."}
            </p>
            {canUpdate && (
              <button onClick={() => update.check(true)} disabled={update.status === "checking" || update.status === "installing"}>
                Check for updates
              </button>
            )}
          </>
        )}
        <button onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
