import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { get, isTauri, post } from "../engine";
import { useStore } from "../store";
import { updatesEnabled, useUpdate } from "../updater";
import { Icon } from "./Icon";
import { ThemeToggle } from "./TopBar";
import { Modal, Switch } from "./ui";

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
    available: `v${update.version} is available.`,
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
    <Modal title="Settings" onClose={onClose} width={560}>
      <section className="section">
        <span className="eyebrow">Appearance</span>
        <ThemeToggle labels />
      </section>

      <section className="section">
        <span className="eyebrow">Speech models · local Whisper</span>
        <div className="list">
          {models.data?.map((m) => (
            <div key={m.name} className="list-row">
              <div className="grow">
                <b>{m.name}</b>
                <small>{m.size_mb} MB · {m.note}</small>
              </div>
              {m.installed ? (
                <span className="tag"><Icon name="check" size={13} /> Installed</span>
              ) : (
                <button className="btn sm" onClick={() => download(m.name)}>
                  <Icon name="download" size={13} />
                  Download
                </button>
              )}
            </div>
          ))}
          {models.isLoading && <div className="list-row muted small">Loading…</div>}
        </div>
      </section>

      <section className="section">
        <span className="eyebrow">AI agents · MCP</span>
        <p className="small muted flush">Lets AI agents use claudebolt to edit your files. Runs locally.</p>
        {!!agents.data?.length && (
          <div className="list">
            {agents.data.map((a) => (
              <div key={a.id} className="list-row">
                <Switch checked={chosen.has(a.id)} onChange={() => toggle(a.id)}>
                  <b>{a.label}</b>
                  {!a.detected && <small>Not detected on this computer</small>}
                </Switch>
              </div>
            ))}
          </div>
        )}
        <div>
          <button className="btn" onClick={install} disabled={chosen.size === 0}>
            <Icon name="sparkle" size={14} />
            Install in selected agents
          </button>
        </div>
        {mcp && <pre className="code">{mcp}</pre>}
      </section>

      {appVersion && (
        <section className="section">
          <span className="eyebrow">Updates</span>
          <div className="list">
            <div className="list-row">
              <div className="grow">
                <b>claudebolt v{appVersion}</b>
                <small>{canUpdate ? updateText[update.status] ?? "" : "Built from source: automatic updates are off."}</small>
              </div>
              {canUpdate && (
                <button className="btn sm" onClick={() => update.check(true)} disabled={update.status === "checking" || update.status === "installing"}>
                  <Icon name="refresh" size={13} />
                  Check for updates
                </button>
              )}
            </div>
          </div>
        </section>
      )}
    </Modal>
  );
}
