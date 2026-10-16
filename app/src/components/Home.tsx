import { useState } from "react";
import { pickFiles } from "../engine";
import { useStore } from "../store";

export function Home() {
  const open = useStore((s) => s.open);
  const [path, setPath] = useState("");

  const browse = async () => {
    const files = await pickFiles();
    if (files && files.length) await open(files);
  };

  return (
    <div className="center home">
      <h1>claudebolt</h1>
      <p className="muted">Cut silences, filler words and retakes from video and audio. Everything runs on this computer.</p>
      <button className="primary big" onClick={browse}>Open video or audio...</button>
      <div className="row">
        <input
          placeholder="or paste a file path"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && path && open([path.replace(/^"|"$/g, "")])}
        />
        <button disabled={!path} onClick={() => open([path.replace(/^"|"$/g, "")])}>Open</button>
      </div>
      <p className="muted small">Drop several files to treat them as separate microphone tracks.</p>
    </div>
  );
}
