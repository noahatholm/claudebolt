import { useEffect, useState } from "react";
import { get } from "../engine";
import { useStore } from "../store";
import type { Detection } from "../types";

interface Analysis {
  suggested_threshold: number;
  histogram: { edges: number[]; counts: number[] };
  warnings: string[];
}

const DEFAULTS: Detection = {
  mode: "rms", threshold: -35, grace: 0.5, pad_left: 0.01, pad_right: 0.15,
  min_keep: 0.75, silence_action: "cut", speed_rate: 3,
};

export function DetectionPanel() {
  const { project, settings, detect, summary } = useStore();
  const [d, setD] = useState<Detection>(DEFAULTS);
  const [an, setAn] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (settings?.detection) setD({ ...DEFAULTS, ...settings.detection });
  }, [settings]);

  useEffect(() => {
    if (!project) return;
    get<Analysis>(`/projects/${project.id}/analyze`).then(setAn).catch(() => setAn(null));
  }, [project?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const num = (k: keyof Detection) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setD({ ...d, [k]: parseFloat(e.target.value) });
  const thr = d.threshold === "auto" ? an?.suggested_threshold ?? -35 : d.threshold;
  const max = Math.max(1, ...(an?.histogram.counts ?? [1]));

  const run = async () => {
    setBusy(true);
    await detect(d);
    setBusy(false);
  };

  return (
    <div className="panel">
      <h3>Silence detection</h3>
      <label>Mode
        <select value={d.mode} onChange={(e) => setD({ ...d, mode: e.target.value as Detection["mode"] })}>
          <option value="rms">Volume (RMS)</option>
          <option value="vad">Speech (VAD)</option>
          <option value="both">Both</option>
        </select>
      </label>
      <div className="hist" title="loudness histogram; the line is the threshold">
        {an?.histogram.counts.map((c, i) => (
          <i key={i} style={{ height: `${(c / max) * 100}%` }} />
        ))}
        {an && (
          <b className="thr" style={{ left: `${((thr + 90) / 90) * 100}%` }} />
        )}
      </div>
      <label>Threshold: {typeof thr === "number" ? thr.toFixed(0) : thr} dB
        <input type="range" min={-80} max={-10} step={1} value={thr} onChange={(e) => setD({ ...d, threshold: parseFloat(e.target.value) })} />
      </label>
      <button onClick={() => an && setD({ ...d, threshold: Math.round(an.suggested_threshold) })}>
        Auto ({an ? an.suggested_threshold.toFixed(0) : "..."} dB)
      </button>
      {an?.warnings.map((w) => <div key={w} className="warn">{w}</div>)}
      <label>Grace (s) <input type="number" step={0.1} min={0} value={d.grace} onChange={num("grace")} /></label>
      <label>Pad left (s) <input type="number" step={0.01} min={0} value={d.pad_left} onChange={num("pad_left")} /></label>
      <label>Pad right (s) <input type="number" step={0.01} min={0} value={d.pad_right} onChange={num("pad_right")} /></label>
      <label>Min keep (s) <input type="number" step={0.05} min={0} value={d.min_keep} onChange={num("min_keep")} /></label>
      <label>Silences
        <select value={d.silence_action} onChange={(e) => setD({ ...d, silence_action: e.target.value as Detection["silence_action"] })}>
          <option value="cut">Cut</option>
          <option value="speed">Speed up</option>
        </select>
      </label>
      {d.silence_action === "speed" && (
        <label>Speed rate <input type="number" step={0.5} min={1.1} value={d.speed_rate} onChange={num("speed_rate")} /></label>
      )}
      <button className="primary" disabled={busy} onClick={run}>{busy ? "Detecting..." : "Detect"}</button>
      {summary && <div className="muted small">-{summary.percent_removed}% ({summary.removed_seconds.toFixed(1)}s removed)</div>}
    </div>
  );
}
