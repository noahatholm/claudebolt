import { useState } from "react";
import { pickSavePath, post } from "../engine";
import { useStore } from "../store";
import type { Job } from "../types";
import { Icon } from "./Icon";
import { Modal, Notice, Progress, Segmented, Switch } from "./ui";

const PRESETS: { label: string; note: string; ext: string; settings: object }[] = [
  { label: "Same as source", note: "Keep the original format", ext: "", settings: {} },
  { label: "MP4 · H.264", note: "High quality, CRF 18", ext: "mp4", settings: { crf: 18 } },
  { label: "MP4 · compact", note: "Smaller upload, CRF 23", ext: "mp4", settings: { crf: 23 } },
  { label: "MP3", note: "Podcast audio", ext: "mp3", settings: {} },
  { label: "WAV", note: "Uncompressed audio", ext: "wav", settings: {} },
  { label: "M4A", note: "AAC audio", ext: "m4a", settings: {} },
];
const EXPORTS: { format: string; label: string; note: string }[] = [
  { format: "fcpxml", label: "FCPXML", note: "Final Cut Pro" },
  { format: "xmeml", label: "XML", note: "Premiere, Resolve" },
  { format: "edl", label: "EDL", note: "Edit decision list" },
  { format: "srt", label: "SRT", note: "Subtitles" },
  { format: "vtt", label: "VTT", note: "Web subtitles" },
  { format: "audacity", label: "Labels", note: "Audacity" },
  { format: "cutlist", label: "Cut list", note: "Plain list of cuts" },
];

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
  const rendering = job?.status === "running" || job?.status === "queued";

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
    <Modal onClose={onClose} title="Export" subtitle="Render a new file, or hand the edit to another editor.">
      <section className="section">
        <span className="eyebrow">Render</span>
        <div className="choices">
          {PRESETS.map((p, i) => (
            <button key={p.label} className={preset === i ? "choice on" : "choice"} onClick={() => setPreset(i)}>
              <b>{p.label}</b>
              <span>{p.note}</span>
            </button>
          ))}
        </div>
        {src.kind === "video" && (
          <div className="row between">
            <Segmented
              value={encoder}
              onChange={setEncoder}
              options={[
                { value: "libx264", label: "CPU (x264)" },
                { value: "auto", label: "GPU if available" },
              ]}
            />
            <Switch checked={zoom} onChange={setZoom}>Punch-zoom alternate cuts</Switch>
          </div>
        )}
        <button className="btn primary lg block" onClick={render} disabled={rendering}>
          {rendering ? <span className="spinner" /> : <Icon name="export" />}
          {rendering ? "Rendering…" : "Render"}
        </button>
        {job && (
          <div className="stack">
            {job.status !== "done" && job.status !== "failed" && (
              <div className="row">
                <div className="grow"><Progress value={job.progress} /></div>
                <span className="small muted mono">{Math.round(job.progress * 100)}%</span>
              </div>
            )}
            {job.status === "done" && <Notice tone="ok">Saved {(job.result as { path?: string })?.path}</Notice>}
            {job.error && <Notice tone="error">{job.error}</Notice>}
          </div>
        )}
      </section>

      <section className="section">
        <span className="eyebrow">Export for other editors</span>
        <div className="choices">
          {EXPORTS.filter((f) => words.length || !["srt", "vtt"].includes(f.format)).map((f) => (
            <button key={f.format} className="choice" onClick={() => doExport(f.format)}>
              <b className="row">
                <Icon name="download" size={13} />
                {f.label}
              </b>
              <span>{f.note}</span>
            </button>
          ))}
        </div>
        {msg && <Notice tone="ok">{msg}</Notice>}
      </section>
    </Modal>
  );
}
