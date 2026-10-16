import { useState } from "react";
import { pickFiles } from "../engine";
import { useStore } from "../store";
import { Icon, type IconName } from "./Icon";

const FEATURES: { icon: IconName; title: string; text: string }[] = [
  { icon: "waveform", title: "Silences", text: "Cut dead air or speed it up, tuned against a live loudness histogram." },
  { icon: "scissors", title: "Speech cleanup", text: "Find filler words, false starts and retakes in a local Whisper transcript." },
  { icon: "sparkle", title: "Agent-ready", text: "A local MCP server lets AI agents analyze, edit, render and export." },
];

export function Home() {
  const open = useStore((s) => s.open);
  const [path, setPath] = useState("");
  const openPath = () => path && open([path.replace(/^"|"$/g, "")]);

  const browse = async () => {
    const files = await pickFiles();
    if (files && files.length) await open(files);
  };

  return (
    <div className="home">
      <div className="home-inner">
        <div className="hero">
          <h1>
            Cut the dead air.
            <br />
            <em>Keep the take.</em>
          </h1>
          <p>Remove silences, filler words and retakes from video and audio. Everything runs on this computer.</p>
        </div>

        <div className="drop">
          <span className="drop-icon"><Icon name="arrowUp" size={24} /></span>
          <button className="btn primary lg" onClick={browse}>
            <Icon name="folder" />
            Open video or audio
          </button>
          <span className="small muted">Select several files to treat them as separate microphone tracks.</span>
          <div className="or">or paste a path</div>
          <div className="pathbar">
            <input
              className="input"
              placeholder="Paste a file path and press Enter"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && openPath()}
            />
            <button className="btn" disabled={!path} onClick={openPath}>Open</button>
          </div>
        </div>

        <div className="features">
          {FEATURES.map((f) => (
            <div key={f.title} className="feature">
              <Icon name={f.icon} size={18} />
              <b>{f.title}</b>
              <span>{f.text}</span>
            </div>
          ))}
        </div>

        <span className="foot-note">
          <Icon name="lock" size={13} /> Local Whisper transcription. No uploads, no accounts.
        </span>
      </div>
    </div>
  );
}
