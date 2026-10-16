import { useEffect, useState } from "react";
import { Editor } from "./components/Editor";
import { Home } from "./components/Home";
import { Icon, Logo } from "./components/Icon";
import { Settings } from "./components/Settings";
import { TopBar } from "./components/TopBar";
import { UpdateBanner } from "./components/UpdateBanner";
import { connect, openEvents } from "./engine";
import { useStore } from "./store";
import { startUpdateChecks } from "./updater";

export function App() {
  const { project, error, setError, setConnected, onEvent } = useStore();
  const [showSettings, setShowSettings] = useState(false);
  const [boot, setBoot] = useState<{ text: string; failed: boolean } | null>({ text: "Starting engine", failed: false });

  useEffect(() => {
    connect()
      .then(() => setBoot(null))
      .catch((e) => setBoot({ text: String(e.message ?? e), failed: true }));
    return openEvents(onEvent, setConnected);
  }, [onEvent, setConnected]);
  useEffect(startUpdateChecks, []);

  if (boot) {
    return (
      <div className="boot">
        <div className={boot.failed ? "boot-inner failed" : "boot-inner"}>
          <Logo size={44} />
          <span>{boot.text}</span>
        </div>
      </div>
    );
  }

  const openSettings = () => setShowSettings(true);
  return (
    <div className="app">
      {project ? (
        <Editor onSettings={openSettings} />
      ) : (
        <>
          <TopBar onSettings={openSettings} />
          <Home />
        </>
      )}
      <div className="toasts">
        <UpdateBanner />
        {error && (
          <div className="toast error" role="alert">
            <span className="t-icon"><Icon name="alert" size={14} /></span>
            <div className="t-body">{error}</div>
            <button className="btn icon sm ghost" onClick={() => setError(null)} aria-label="Dismiss">
              <Icon name="x" size={14} />
            </button>
          </div>
        )}
      </div>
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
    </div>
  );
}
