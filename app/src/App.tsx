import { useEffect, useState } from "react";
import { Editor } from "./components/Editor";
import { Home } from "./components/Home";
import { Settings } from "./components/Settings";
import { connect, openEvents } from "./engine";
import { useStore } from "./store";

export function App() {
  const { project, error, setError, setConnected, onEvent, connected } = useStore();
  const [showSettings, setShowSettings] = useState(false);
  const [boot, setBoot] = useState<string | null>("Starting engine...");

  useEffect(() => {
    connect()
      .then(() => setBoot(null))
      .catch((e) => setBoot(String(e.message ?? e)));
    return openEvents(onEvent, setConnected);
  }, [onEvent, setConnected]);

  if (boot) return <div className="center muted">{boot}</div>;

  return (
    <div className="app">
      <header className="topbar">
        <strong>claudebolt</strong>
        <span className={connected ? "dot ok" : "dot"} title={connected ? "engine connected" : "reconnecting"} />
        <span className="spacer" />
        <button onClick={() => setShowSettings(true)}>Settings</button>
      </header>
      {error && (
        <div className="error" onClick={() => setError(null)}>
          {error} <small>(click to dismiss)</small>
        </div>
      )}
      {project ? <Editor /> : <Home />}
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
    </div>
  );
}
