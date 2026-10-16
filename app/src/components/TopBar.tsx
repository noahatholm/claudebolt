import type { ReactNode } from "react";
import { useStore } from "../store";
import { useTheme } from "../theme";
import { Icon, Logo } from "./Icon";
import { Segmented } from "./ui";

export function ThemeToggle({ labels }: { labels?: boolean }) {
  const { pref, setPref } = useTheme();
  return (
    <Segmented
      value={pref}
      onChange={setPref}
      iconOnly={!labels}
      full={labels}
      options={[
        { value: "system", label: "System", icon: "monitor", hint: "Match the system appearance" },
        { value: "light", label: "Light", icon: "sun" },
        { value: "dark", label: "Dark", icon: "moon" },
      ]}
    />
  );
}

export function TopBar({ onSettings, file, children }: { onSettings: () => void; file?: string; children?: ReactNode }) {
  const connected = useStore((s) => s.connected);
  const name = file?.split(/[\\/]/).pop();
  return (
    <header className="topbar">
      <div className="brand">
        <Logo />
        <span>claudebolt</span>
      </div>
      {name && (
        <>
          <span className="crumb-sep">/</span>
          <span className="crumb" title={file}>{name}</span>
        </>
      )}
      <span className={connected ? "status ok" : "status"} title={connected ? "Local engine connected" : "Reconnecting to the local engine"}>
        <i />
        {connected ? "Local" : "Reconnecting"}
      </span>
      <span className="spacer" />
      {children}
      {children && <span className="divider" />}
      <ThemeToggle />
      <button className="btn icon ghost" onClick={onSettings} title="Settings" aria-label="Settings">
        <Icon name="sliders" />
      </button>
    </header>
  );
}
