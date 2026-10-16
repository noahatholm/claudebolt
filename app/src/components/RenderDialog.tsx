import { useState } from "react";
import { pickSavePath, post } from "../engine";
import { useStore } from "../store";
import type { Job } from "../types";

const PRESETS: { label: string; ext: string; settings: object }[] = [
  { label: "Same as source", ext: "", settings: {} },
  { label: "MP4 (H.264)", ext: "mp4", settings: { crf: 18 } },
  { label: "MP4 small (YouTube-ish)", ext: "mp4", settings: { crf: 23 } },
  { label: "Podcast MP3", ext: "mp3", settings: {} },
  { label: "WAV", ext: "wav", settings: {} },
  { label: "M4A (AAC)", ext: "m4a", settings: {} },
];
const EXPORTS = ["fcpxml", "xmeml", "edl", "srt", "vtt", "audacity", "cutlist"];

export function RenderDialog({ onClose }: { onClose: () => void }) {
  const { project, jobs, setError, words } = useStore();
  const [preset, setPreset] = useState(0);
  const [encoder, setEncoder] = useState("libx264");
  const [zoom, setZoom] = useState(false);
  const [msg, setMsg] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  if (!project) return null;
  const src = project.sources[0];
  const stem = src.path.replace(/\.[^.\\/]+$/, "");
  const srcExt = src.path.split(".").pop() ?? "mp4";
  const job: Job | undefined = jobId ? jobs[jobId] : undefined;

  const render = async () => {
    const p = PRESETS[preset];
    const ext = p.ext || srcExt;
    const target = (await pickSavePath(`${stem}.edited.${ext}`)) ?? `${stem}.edited.${ext}`;
    try {
      const j = await post<Job>(`/projects/${project.id}/render`, {
        output_path: target,
        settings: { ...p.settings, encoder_pref: encoder, zoom_mode: zoom ? "alternate" : "none" },
      });
      setJobId(j.job_id);
      setMsg("");
    } catch (e) {
      setError(e);
    }
  };

  const doExport = async (format: string) => {
    try {
      const r = await post<{ path: string }>(`/projects/${project.id}/export`, { format });
      setMsg(`Wrote ${r.path}`);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div className="modal" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h3>Render</h3>
        <label>Preset
          <select value={preset} onChange={(e) => setPreset(+e.target.value)}>
            {PRESETS.map((p, i) => <option key={p.label} value={i}>{p.label}</option>)}
          </select>
        </label>
        {src.kind === "video" && (
          <>
            <label>Encoder
              <select value={encoder} onChange={(e) => setEncoder(e.target.value)}>
                <option value="libx264">CPU (x264)</option>
                <option value="auto">Auto (GPU if available)</option>
              </select>
            </label>
            <label className="check"><input type="checkbox" checked={zoom} onChange={(e) => setZoom(e.target.checked)} /> Punch-zoom alternate cuts</label>
          </>
        )}
        <button className="primary" onClick={render} disabled={job?.status === "running"}>Render</button>
        {job && (
          <div>
            <progress value={job.progress} max={1} /> {job.status}
            {job.status === "done" && <div className="ok-text">Saved {(job.result as { path?: string })?.path}</div>}
            {job.error && <div className="error">{job.error}</div>}
          </div>
        )}
        <h3>Export for other editors</h3>
        <div className="row wrap">
          {EXPORTS.filter((f) => words.length || !["srt", "vtt"].includes(f)).map((f) => (
            <button key={f} onClick={() => doExport(f)}>{f}</button>
          ))}
        </div>
        {msg && <div className="ok-text">{msg}</div>}
        <button onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
