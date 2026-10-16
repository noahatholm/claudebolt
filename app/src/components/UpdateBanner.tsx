import { useStore } from "../store";
import { useUpdate } from "../updater";

/** "vX.Y.Z is available": installs (and restarts) only when clicked. */
export function UpdateBanner() {
  const { status, version, progress, error, dismissed, install, dismiss } = useUpdate();
  const busy = useStore((s) => Object.values(s.jobs).some((j) => j.status === "queued" || j.status === "running"));

  if (status === "installing") {
    const pct = progress == null ? "" : ` ${Math.round(progress * 100)}%`;
    return <div className="update">Downloading claudebolt v{version}...{pct} The app restarts when it is installed.</div>;
  }
  if (status === "error" && version) {
    return (
      <div className="update">
        Could not install v{version}: {error} <button onClick={install}>Retry</button> <button onClick={dismiss}>Later</button>
      </div>
    );
  }
  if (status !== "available" || dismissed) return null;
  const go = () => {
    if (busy && !confirm("A job is still running. Installing restarts claudebolt and stops it. Install now?")) return;
    void install();
  };
  return (
    <div className="update">
      claudebolt v{version} is available. <button onClick={go}>Install &amp; restart</button>{" "}
      <button onClick={dismiss}>Later</button>
    </div>
  );
}
