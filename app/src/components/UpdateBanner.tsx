import { useStore } from "../store";
import { useUpdate } from "../updater";
import { Icon } from "./Icon";
import { Progress } from "./ui";

/** "vX.Y.Z is available": installs (and restarts) only when clicked. */
export function UpdateBanner() {
  const { status, version, progress, error, dismissed, install, dismiss } = useUpdate();
  const busy = useStore((s) => Object.values(s.jobs).some((j) => j.status === "queued" || j.status === "running"));

  if (status === "installing") {
    return (
      <div className="toast info">
        <span className="t-icon"><Icon name="download" size={14} /></span>
        <div className="t-body">
          <span>Downloading claudebolt v{version}. The app restarts when it is installed.</span>
          {progress != null && <Progress value={progress} />}
        </div>
      </div>
    );
  }
  if (status === "error" && version) {
    return (
      <div className="toast error">
        <span className="t-icon"><Icon name="alert" size={14} /></span>
        <div className="t-body">
          <span>Could not install v{version}: {error}</span>
          <div className="t-actions">
            <button className="btn sm" onClick={install}>Retry</button>
            <button className="btn sm ghost" onClick={dismiss}>Later</button>
          </div>
        </div>
      </div>
    );
  }
  if (status !== "available" || dismissed) return null;
  const go = () => {
    if (busy && !confirm("A job is still running. Installing restarts claudebolt and stops it. Install now?")) return;
    void install();
  };
  return (
    <div className="toast info">
      <span className="t-icon"><Icon name="sparkle" size={14} /></span>
      <div className="t-body">
        <span>claudebolt v{version} is available.</span>
        <div className="t-actions">
          <button className="btn sm primary" onClick={go}>Install &amp; restart</button>
          <button className="btn sm ghost" onClick={dismiss}>Later</button>
        </div>
      </div>
    </div>
  );
}
